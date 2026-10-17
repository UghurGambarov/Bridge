"""Chinese summary card (SPEC §9.3).

Every number and fact comes from a deterministic template filled from the validated extracted
fields, the registry and the FX tool — never from model text. A real model may add one or two
plain sentences of explanation, labelled AI生成; mock mode uses the template only.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlmodel import Session

from ..models import Document, Institution
from ..sandbox import fx
from ..security import injection

SYMBOLS = {"GBP": "£", "USD": "US$", "HKD": "HK$", "EUR": "€", "CNY": "¥"}
COUNTRY_ZH = {"UK": "英国", "US": "美国", "HK": "中国香港"}
COUNTRY_EN = {"UK": "UK", "US": "US", "HK": "Hong Kong"}
KIND_ZH = {"tuition": "学费账单", "accommodation": "住宿费账单", "deposit": "押金账单"}
KIND_EN = {"tuition": "tuition invoice", "accommodation": "accommodation invoice", "deposit": "deposit invoice"}
DOCTYPE_ZH = {"message": "消息", "email": "邮件", "letter": "信函", "notice": "通知", "unknown": "文件"}
SIGNAL_ZH = {
    "PAYEE_NOT_IN_REGISTRY": "收款方不在核验名单中",
    "ACCOUNT_MISMATCH": "账号与学校登记的账号不一致",
    "NAME_MISMATCH": "收款人名称与登记名称不一致",
    "PERSONAL_ACCOUNT_FOR_FEES": "要求把学费付到个人账户",
    "REFERENCE_FORMAT_MISMATCH": "参考号格式不符",
    "LOOKALIKE_DOMAIN": "发件域名仿冒学校官方域名",
    "BANK_DETAILS_CHANGE_REQUEST": "要求更改收款账户",
    "HIDDEN_TEXT": "文件中有肉眼看不见的隐藏文字",
    "INJECTION_PHRASE": "文件中有针对AI的指令",
    "INVISIBLE_UNICODE": "文字中藏有不可见字符",
    "DISCOUNT_OFFER": "声称学费打折",
    "URGENCY": "催促尽快付款",
    "AGENCY_INTERMEDIARY": "中介声称“代缴”学费",
    "CRYPTO_MENTION": "要求用加密货币付款",
    "AMOUNT_OUTSIDE_FEE_RANGE": "金额超出学校公布的收费范围",
    "DEADLINE_MISMATCH": "截止日期与学校公布的日期不符",
}


def money(currency: str, amount: Decimal) -> str:
    return f"{SYMBOLS.get(currency, currency + ' ')}{amount:,.2f}"


def cny_round(amount: Decimal) -> str:
    return f"¥{amount:,.0f}" if amount == amount.to_integral_value() else f"¥{amount:,.2f}"


def date_zh(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.year}年{d.month}月{d.day}日"


def date_en(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d %b %Y").lstrip("0")


def safe(text: Optional[str], limit: int = 60) -> str:
    """Untrusted strings shown to the user: strip invisible characters, drop injection, truncate."""
    if not text:
        return ""
    t = injection.strip_invisible(text).replace("\n", " ").strip()
    if injection.scan(t)["injection_hits"]:
        return "[已隐藏可疑文字 / suspicious text hidden]"
    return t[:limit]


def build(session: Session, doc: Document) -> dict:
    ex = doc.extracted_json or {}
    pc = doc.payee_check_json or {}
    inst = session.get(Institution, pc["institution_id"]) if pc.get("institution_id") else None
    purpose = pc.get("purpose_guess", "tuition")
    numbers: dict = {}
    zh: list[str] = []
    en: list[str] = []

    issuer = inst.name if inst else safe(ex.get("issuer_name")) or "未知发件方"
    if inst and ex.get("doc_type") == "invoice":
        zh.append(f"这是一张来自 {inst.name}（{COUNTRY_ZH.get(inst.country, inst.country)}）的{KIND_ZH.get(purpose, '账单')}。")
        en.append(f"This is a {KIND_EN.get(purpose, 'invoice')} from {inst.name} ({COUNTRY_EN.get(inst.country, inst.country)}).")
    else:
        kind = ex.get("doc_type", "unknown")
        zh.append(f"这是一份来自 {issuer} 的{KIND_ZH.get(purpose, '账单') if kind == 'invoice' else DOCTYPE_ZH.get(kind, '文件')}。")
        en.append(f"This is a {kind} from {issuer}.")

    if ex.get("amount") is not None and ex.get("currency"):
        cur = ex["currency"]
        amount = Decimal(str(ex["amount"]))
        try:
            q = fx.quote(cur, amount)
            numbers.update({"amount": f"{amount:.2f}", "currency": cur, "cny": f"{q.cny_amount:.2f}",
                            "rate": f"{q.rate_cny:.2f}", "usd_equivalent": f"{q.usd_equivalent:.2f}"})
            zh.append(f"金额：{money(cur, amount)}（约 {cny_round(q.cny_amount)}，按模拟汇率 {q.rate_cny:.2f} 计算）。")
            en.append(f"Amount: {money(cur, amount)} (≈ {cny_round(q.cny_amount)} at the simulated rate {q.rate_cny:.2f}).")
        except (fx.UnsupportedCurrency, ValueError):
            numbers.update({"amount": f"{amount:.2f}", "currency": cur})
            zh.append(f"金额：{cur} {amount:,.2f}。")
            en.append(f"Amount: {cur} {amount:,.2f}.")
    if ex.get("due_date"):
        numbers["due_date"] = ex["due_date"]
        zh.append(f"截止日期：{date_zh(ex['due_date'])}。")
        en.append(f"Due: {date_en(ex['due_date'])}.")

    verdict = pc.get("verdict")
    if verdict == "verified":
        zh.append(f"收款方：{pc.get('matched_beneficiary')} —— 已在核验名单中 ✅。")
        en.append(f"Payee: {pc.get('matched_beneficiary')} — verified in the registry ✅.")
    elif verdict in ("blocked", "warning", "unverified"):
        reasons = "、".join(SIGNAL_ZH.get(s["code"], s["code"]) for s in pc.get("signals", [])[:4])
        if verdict == "blocked":
            zh.append(f"⚠️ 风险提示：这份文件没有通过收款方核验（规则 {pc.get('forbidden_rule')}）：{reasons}。请不要付款。")
            en.append(f"⚠️ Warning: this document failed payee verification (rule {pc.get('forbidden_rule')}). Do not pay.")
        else:
            zh.append(f"⚠️ 请注意：{reasons or '收款方尚未核验'}。")
            en.append("⚠️ Caution: the payee is not fully verified.")
    if ex.get("reference"):
        numbers["reference"] = ex["reference"]
        zh.append(f"参考号：{safe(ex['reference'], 30)}。")
        en.append(f"Reference: {safe(ex['reference'], 30)}.")
    for n in pc.get("notices", []):
        if n.startswith("Deadline soon"):
            days = n.split("due in ")[1].split(" ")[0]
            zh.append(f"⏰ 距离截止日期还有 {days} 天。")
            en.append(f"⏰ {n}")

    return {
        "type": "zh_summary",
        "doc_id": doc.id,
        "zh": "".join(zh),
        "en": " ".join(en),
        "numbers": numbers,
        "verdict": verdict,
        "source": "template",
        "ai_note": None,
        "review_note": "Chinese wording to be reviewed by a native speaker (known risk R-06).",
    }


def add_ai_note(card: dict, provider) -> dict:
    """Optional 1-2 sentence explanation from a real model, labelled AI生成. Numbers are not touched."""
    if provider is None or provider.is_mock or card.get("verdict") == "blocked":
        return card
    try:
        note = provider.explain(
            "用一两句简单的中文解释账单里的英文术语（例如 term、tuition、accommodation）。不要写任何数字、金额、日期或账号。",
            f"Document type: {card.get('verdict')} invoice. English summary: {card['en']}",
        )
    except Exception:
        return card
    note = safe(note, 160)
    if note and not any(ch.isdigit() for ch in note):
        card["ai_note"] = {"text": note, "label": "AI生成 · AI-generated"}
    return card
