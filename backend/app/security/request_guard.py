"""Request guard (SPEC §9.7): deterministic pre-screen of chat messages and document text.

A hit attaches a `refusal` card and is logged. The refusal is guaranteed even if the
model's reply is sloppy, because it does not depend on the model at all.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from ..config import rule
from .injection import strip_invisible

_REL_EN = r"(?:brother|sister|uncle|aunt|wife|husband|mother|father|mom|mum|dad|son|daughter|cousin|friend|relatives?|parents?|grand(?:mother|father|ma|pa))"
_REL_ZH = r"(?:哥哥|弟弟|姐姐|妹妹|舅舅|叔叔|伯伯|姑姑|阿姨|姨妈|亲戚|老公|丈夫|妻子|老婆|爸爸|妈妈|父亲|母亲|爷爷|奶奶|外公|外婆|朋友|家人)"

PATTERNS: dict[str, tuple[str, list[str]]] = {
    "other_persons_quota": ("T4-003", [
        rf"\b(?:use|using|borrow|borrowing|take)\b.{{0,20}}\b{_REL_EN}(?:'s|s|’s)?\b.{{0,15}}\bquotas?\b",
        r"\b(?:his|her|their|someone else'?s|another person'?s)\s+(?:fx\s+)?quota\b",
        r"\b(?:combine|pool|add up|merge)\b.{0,20}\bquotas?\b",
        r"\bfamily quota\b",
        rf"用(?:我|他|她)?{_REL_ZH}的(?:购汇)?额度",
        r"借(?:用)?.{0,6}额度", r"分(?:开|拆)购汇", r"额度.{0,4}(?:合并|凑)",
    ]),
    "split_to_avoid_approval": ("T2-003", [
        r"\bsplit\b.{0,20}\binto\b.{0,15}\b(?:several|small|smaller|multiple|many|\d+)\b.{0,10}\b(?:payments|transfers|parts|pieces)\b",
        r"\b(?:so|so that)\s+it\s+(?:doesn'?t|does not|won'?t|will not)\s+need\s+(?:an\s+)?approval\b",
        r"\b(?:avoid|dodge|get around)\b.{0,15}\bapprovals?\b",
        r"\bstay\s+under\s+the\s+(?:cap|limit)\b",
        r"拆分", r"分几笔", r"分成.{0,3}笔", r"不需要审批",
    ]),
    "private_fx": ("T4-004", [
        r"\bprivate\s+(?:fx|exchange|currency\s+exchange|money\s+exchange)\b",
        r"\b(?:better|cheaper|preferential)\s+rate\b.{0,30}\b(?:wechat|group|private|friend)\b",
        r"\bwechat\s+group\b.{0,30}\b(?:rate|exchange|fx)\b",
        r"\bunderground\s+bank\b", r"\bblack\s+market\b",
        r"私下换汇", r"地下钱庄", r"换汇群", r"优惠汇率", r"黑市",
    ]),
    "crypto": ("T4-005", [
        r"\busdt\b", r"\busdc\b", r"\bstable\s?coins?\b", r"\bbitcoin\b", r"\bbtc\b", r"\bethereum\b",
        r"\bcrypto(?:currency|currencies)?\b", r"\b0x[a-fA-F0-9]{8,}\b",
        r"泰达币", r"稳定币", r"虚拟货币", r"加密货币", r"比特币",
    ]),
    "bypass_controls": ("T4-008", [
        r"\b(?:admin|administrator|developer|dev|debug|god|maintenance)\s+mode\b",
        r"\bignore\b.{0,20}\b(?:rules|instructions|controls|policy|policies)\b",
        r"\bskip\b.{0,10}\bapprovals?\b", r"\bwithout\s+(?:any\s+)?approvals?\b",
        r"\bdisable\b.{0,15}\b(?:checks|controls|security|approvals?|policy)\b",
        r"\bbypass\b", r"\bapprovals?\b.{0,25}\b(?:disabled|suspended|turned off|not required)\b",
        r"\bpre-?approved\b",
        r"跳过审批", r"无需(?:审批|确认)", r"管理员模式", r"开发者模式", r"忽略.{0,4}规则", r"关闭.{0,4}(?:审批|检查)",
    ]),
}

_COMPILED = {cat: (rid, [re.compile(p, re.IGNORECASE) for p in pats]) for cat, (rid, pats) in PATTERNS.items()}


@dataclass
class GuardHit:
    rule_id: str
    category: str
    matched: str

    def as_dict(self) -> dict:
        return asdict(self)


def screen(text: str) -> list[GuardHit]:
    norm = unicodedata.normalize("NFKC", strip_invisible(text or ""))
    norm = norm.replace("’", "'")
    hits: list[GuardHit] = []
    for cat, (rid, pats) in _COMPILED.items():
        for p in pats:
            m = p.search(norm)
            if m:
                hits.append(GuardHit(rule_id=rid, category=cat, matched=m.group(0)))
                break
    return hits


def refusal_card(rule_id: str, matched: str = "") -> dict:
    """The `refusal` card: {rule_id, title, explanation, lawful_alternative, source}."""
    r = rule(rule_id)
    return {
        "type": "refusal",
        "rule_id": rule_id,
        "title": r["title"],
        "explanation": r["text"],
        "lawful_alternative": r.get("lawful_alternative", ""),
        "source": r.get("source", ""),
        "status": r.get("status", "to_verify"),
        "matched": matched,
    }


def screen_and_log(session, text: str, *, source: str = "chat", persona: str | None = None) -> list[GuardHit]:
    """Screen text and write one audit entry per hit (refusals are always logged)."""
    from . import audit

    hits = screen(text)
    for h in hits:
        audit.append(session, actor="policy", persona=persona, event="request_guard_hit", rule_id=h.rule_id,
                     decision="deny", reason=f"{h.category}: refused before reaching the planner",
                     payload={"source": source, "category": h.category, "matched": h.matched})
    return hits
