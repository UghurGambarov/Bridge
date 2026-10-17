"""Deterministic, keyword-scripted planner and extractor for tests, CI and offline demos.

It behaves like a well-behaved model: it reads only the structured context the orchestrator
gives it (never raw document text), uses tools for every figure, and replies in the user's
language. It is NOT a security boundary — the policy engine is.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from .base import LLMProvider, LLMResponse, ToolCall

CONTEXT_PREFIX = "BRIDGE_CONTEXT: "


def parse_turn(messages: list[dict]) -> tuple[str, dict, list[tuple[str, dict]]]:
    """Return (user text, context dict, [(tool name, result)] for the current turn)."""
    last_user = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=-1)
    text, ctx = "", {}
    if last_user >= 0:
        content = messages[last_user].get("content") or ""
        lines = []
        for ln in content.splitlines():
            if ln.startswith(CONTEXT_PREFIX):
                try:
                    ctx = json.loads(ln[len(CONTEXT_PREFIX):])
                except json.JSONDecodeError:
                    ctx = {}
            else:
                lines.append(ln)
        text = "\n".join(lines).strip()
    results = []
    for m in messages[last_user + 1:]:
        if m["role"] == "tool":
            try:
                results.append((m.get("name", ""), json.loads(m.get("content") or "{}")))
            except json.JSONDecodeError:
                results.append((m.get("name", ""), {}))
    return text, ctx, results


def latest_intent(messages: list[dict], status: Optional[tuple] = None) -> Optional[dict]:
    for m in reversed(messages):
        if m["role"] != "tool":
            continue
        try:
            res = json.loads(m.get("content") or "{}")
        except json.JSONDecodeError:
            continue
        intent = res.get("intent") if isinstance(res, dict) else None
        if intent and intent.get("intent_id") and (status is None or intent.get("status") in status):
            return intent
    return None


def is_zh(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text or ""))


_AMOUNT_RE = re.compile(r"(?:£|GBP\s*|英镑\s*)([\d,]+(?:\.\d{1,2})?)|([\d,]+(?:\.\d{1,2})?)\s*(?:英镑|GBP|pounds?)", re.I)


def _amount(text: str) -> Optional[str]:
    m = _AMOUNT_RE.search(text or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).replace(",", "")


class MockLLM(LLMProvider):
    provider = "mock"
    model = "mock-planner-v1"

    @property
    def label(self) -> str:
        return "MOCK — tests only"

    def __init__(self) -> None:
        self._n = 0

    def _call(self, name: str, **args: Any) -> LLMResponse:
        self._n += 1
        return LLMResponse(tool_calls=[ToolCall(id=f"call_{self._n}", name=name, arguments=args)])

    @staticmethod
    def _say(text: str) -> LLMResponse:
        return LLMResponse(text=text)

    # ------------------------------------------------------------------ planner
    def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        text, ctx, results = parse_turn(messages)
        zh = ctx.get("language") == "zh" or is_zh(text)
        done = [n for n, _ in results]
        res = {n: r for n, r in results}
        low = text.lower()

        # 1. Events from the backend.
        if ctx.get("event") == "approvals_complete":
            intent_id = ctx.get("intent_id")
            if "execute_payment" not in done:
                return self._call("execute_payment", intent_id=intent_id)
            r = res["execute_payment"]
            if r.get("executed"):
                return self._say(f"付款已在沙盒银行完成，银行参考号 {r.get('bank_reference')}，收据已生成。" if zh else
                                 f"Both approvals are in. Paid in the sandbox bank: reference {r.get('bank_reference')}. The receipt is ready.")
            return self._say(f"付款未执行：{r.get('rule_id')}。" if zh else f"The payment was not executed: {r.get('rule_id')} — {r.get('reason', '')}")

        # 2. Request-guard refusals (deterministic refusal cards are already attached).
        guard = [g["rule_id"] for g in ctx.get("guard", [])]
        forbidden = [g for g in guard if g.startswith("T4-")]
        if forbidden:
            rid = forbidden[0]
            if rid == "T4-003":
                pending = latest_intent(messages, ("awaiting_documents",))
                if pending and "build_document_list" not in done:
                    return self._call("build_document_list", intent_id=pending["intent_id"])
                if zh:
                    return self._say("不可以。额度属于个人，不能使用您哥哥的额度，也不能把一笔学费拆到几个人的额度上（规则 T4-003，分拆购汇会被外汇局处罚）。"
                                     "合法的做法：超出您个人额度的部分，可以凭录取通知书、账单、身份证明和亲属关系证明到银行办理购汇。所需材料清单如下。")
                return self._say("I can't do that: the FX quota belongs to one person, and using a relative's quota or splitting one payment "
                                 "across several people's quotas is prohibited (rule T4-003). The lawful route: buy the amount above your own "
                                 "quota through the bank with the documents in the checklist.")
            msgs = {
                "T4-004": ("不可以使用私下换汇或地下钱庄（规则 T4-004），可能导致银行卡被冻结。请通过持牌银行购汇。",
                           "I can't use private or 'preferential-rate' exchange (rule T4-004); it is illegal and can freeze your cards. Use licensed bank FX."),
                "T4-005": ("Bridge 不会通过加密货币或稳定币转账（规则 T4-005）。请使用银行转账。",
                           "Bridge never routes money through crypto or stablecoins (rule T4-005). Pay by bank transfer to the registered account."),
                "T4-008": ("我不能跳过审批或关闭任何控制（规则 T4-008）。所有付款仍需审批。",
                           "I can't skip approval or disable controls, and there is no admin or developer mode (rule T4-008). Approvals are still required."),
            }
            z, e = msgs.get(rid, ("这个请求被拒绝了（规则 %s）。" % rid, "That request is refused (rule %s)." % rid))
            return self._say(z if zh else e)

        # 3. Uploaded documents: read -> summarise -> verify -> quota -> FX -> intent -> documents -> approval.
        attachments = ctx.get("attachments", [])
        if attachments:
            doc_id = attachments[0]["doc_id"]
            for step in ("read_document", "summarize_in_chinese", "verify_payee"):
                if step not in done:
                    return self._call(step, doc_id=doc_id)
            v = res["verify_payee"]
            fields = res["read_document"].get("fields", {})
            if v.get("verdict") == "blocked":
                inst = v.get("institution_id") or v.get("mentioned_institution_id")
                if inst and "draft_verification_email" not in done:
                    return self._call("draft_verification_email", institution_id=inst, doc_id=doc_id)
                rule = v.get("forbidden_rule")
                if zh:
                    return self._say(f"请不要付款。这份文件没有通过收款方核验（规则 {rule}）。我已起草一封核实邮件，"
                                     "收件人是登记名单中学校的官方邮箱，请您审阅后自行发送。")
                return self._say(f"Please don't pay this. It failed payee verification (rule {rule}). I drafted a verification email "
                                 "to the university's official address from the registry for you to review and send.")
            if v.get("verdict") == "no_payee" or not v.get("matched_channel_id") or fields.get("amount") is None:
                return self._say("这份文件已保存，可用于办理超额度购汇的材料。" if zh else
                                 "I saved this document. It has no payment details; it can support the documented FX route.")
            if "check_quota" not in done:
                return self._call("check_quota", person_id=ctx.get("payer_id", "p_zhang_min"))
            if "get_fx_quote" not in done:
                return self._call("get_fx_quote", currency=fields["currency"], amount=fields["amount"])
            if "create_payment_intent" not in done:
                args = {"purpose": v.get("purpose_guess", "tuition"), "payer_id": ctx.get("payer_id", "p_zhang_min"),
                        "payee_channel_id": v["matched_channel_id"], "amount": fields["amount"],
                        "currency": fields["currency"], "doc_id": doc_id}
                if fields.get("reference"):
                    args["reference"] = fields["reference"]
                return self._call("create_payment_intent", **args)
            intent = res["create_payment_intent"].get("intent")
            if not intent:
                r = res["create_payment_intent"]
                return self._say(f"无法创建付款（规则 {r.get('rule_id')}）。" if zh else
                                 f"I could not prepare the payment (rule {r.get('rule_id')}): {r.get('reason', '')}")
            if "build_document_list" not in done:
                return self._call("build_document_list", intent_id=intent["intent_id"])
            if intent["status"] == "awaiting_documents":
                return self._say("这笔付款超出了您今年剩余的个人购汇额度，需要走凭材料购汇的路线：请准备清单中的材料，银行核验后再进行审批。" if zh else
                                 "This payment is above your remaining personal FX quota, so it goes through the documented route: "
                                 "prepare the documents in the checklist; after the bank verifies them, approvals follow.")
            if intent["status"] in ("draft", "held") and "request_approval" not in done:
                return self._call("request_approval", intent_id=intent["intent_id"])
            fp = intent.get("fingerprint")
            if zh:
                return self._say(f"收款方已核验，额度足够。请在审批窗口确认交易指纹 {fp}，然后请李伟在他的设备上确认同一指纹。")
            return self._say(f"The payee is verified and the payment fits your quota. Please approve fingerprint {fp}; "
                             "then Li Wei confirms the same fingerprint on his device.")

        # 4. Ad-hoc transfer to the student ("Send Li Wei an extra £2,000").
        amount = _amount(text)
        wants_transfer = bool(re.search(r"\bsend\b|\bextra\b|\btransfer\b|\bsplit\b|转|汇|给李伟|额外|零花钱|生活费", low))
        if amount and wants_transfer:
            if "get_family_overview" not in done:
                return self._call("get_family_overview")
            if "create_payment_intent" not in done:
                ov = res["get_family_overview"]
                return self._call("create_payment_intent", purpose="allowance", payer_id=ov["payer_id"],
                                  payee_channel_id=ov["student_channel_id"], amount=amount, currency="GBP")
            r = res["create_payment_intent"]
            intent = r.get("intent")
            if intent and intent["status"] in ("held", "pending_approval") and "request_approval" not in done:
                return self._call("request_approval", intent_id=intent["intent_id"])
            if intent and intent.get("tier") == "T2" and intent["status"] == "draft" and "execute_payment" not in done:
                return self._call("execute_payment", intent_id=intent["intent_id"])
            if intent and intent["status"] in ("held", "pending_approval"):
                return self._say(f"这笔转账超出了自动转账的限额，需要您和李伟审批（指纹 {intent.get('fingerprint')}）。" if zh else
                                 f"This is above the automatic limits, so it is held for approval by you and Li Wei "
                                 f"(fingerprint {intent.get('fingerprint')}).")
            if intent and "execute_payment" in done and res["execute_payment"].get("executed"):
                return self._say("已在限额内自动转给李伟本人的账户。" if zh else "Sent automatically to Li Wei's own verified account, within limits.")
            return self._say(f"无法完成（规则 {r.get('rule_id')}）。" if zh else f"I couldn't do that (rule {r.get('rule_id')}).")

        # 5. Explanations, status, quota.
        if re.search(r"\bwhy\b|explain|为什么|原因", low):
            intent = latest_intent(messages)
            if intent and "explain_decision" not in done:
                return self._call("explain_decision", intent_id=intent["intent_id"])
            if intent:
                return self._say("右侧的“为什么”面板列出了每一条规则检查。" if zh else "The Why panel lists every rule check, with sources.")
        if re.search(r"quota|额度", low):
            if "check_quota" not in done:
                return self._call("check_quota", person_id=ctx.get("payer_id", "p_zhang_min"))
            q = res["check_quota"].get("quota", {})
            return self._say(f"您今年还剩 {q.get('remaining_usd')} 美元的个人购汇额度。" if zh else
                             f"You have USD {q.get('remaining_usd')} of personal FX quota left this year.")
        if re.search(r"status|进度|状态", low):
            intent = latest_intent(messages)
            if intent and "get_status" not in done:
                return self._call("get_status", intent_id=intent["intent_id"])
            if intent:
                st = res.get("get_status", {}).get("intent", intent).get("status")
                return self._say(f"当前状态：{st}。" if zh else f"Current status: {st}.")

        # 6. Vague request: ask a clarifying question (no T1+ tool).
        if "ask_clarifying_question" not in done:
            q = ("请问是哪一张账单？请上传学校的账单，我来核验收款方和额度。" if zh else
                 "Which invoice is this about? Please upload it and I'll verify the payee and your quota.")
            return self._call("ask_clarifying_question", question=q)
        return self._say(res["ask_clarifying_question"].get("question", ""))

    # ------------------------------------------------------------------ extractor
    def extract_json(self, system: str, text: str) -> dict:
        from ..extractor import regex_extract

        return regex_extract(text).model_dump(mode="json")
