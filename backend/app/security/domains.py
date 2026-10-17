"""Lookalike-domain detection (SPEC §9.1): IDNA, confusable skeleton, edit distance, brand tokens."""
from __future__ import annotations

import re
import unicodedata

# Cyrillic and Greek homoglyphs mapped to Latin.
CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j",
    "ѕ": "s", "ԁ": "d", "һ": "h", "ӏ": "l", "к": "k", "м": "m", "н": "h", "т": "t", "в": "b", "г": "r",
    "ԛ": "q", "ԝ": "w", "ɡ": "g",
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
    "χ": "x", "γ": "y", "η": "n", "ω": "w",
    "0": "o", "1": "l",
}

_TLDS = {"com", "net", "org", "edu", "uk", "hk", "cn", "io", "co", "info", "biz", "xyz", "top", "us", "eu",
         "de", "fr", "au", "ca", "sg", "online", "site", "app", "cc", "me", "vip", "shop"}
_EMAIL_RE = re.compile(r"[\w.+-]+@((?:[\w-]+\.)+[\w-]+)", re.UNICODE)
_URL_RE = re.compile(r"https?://((?:[\w-]+\.)+[\w-]+)", re.UNICODE)
_BARE_RE = re.compile(r"(?<![@\w.-])((?:[\w-]+\.)+([A-Za-z]{2,}))(?![\w-])", re.UNICODE)


def to_ascii(domain: str) -> str | None:
    try:
        return domain.encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return None


def skeleton(domain: str) -> str:
    d = unicodedata.normalize("NFKC", domain.lower())
    return "".join(CONFUSABLES.get(ch, ch) for ch in d)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def extract_domains(text: str) -> list[str]:
    found: list[str] = []
    for rx in (_EMAIL_RE, _URL_RE):
        found += [m.group(1) for m in rx.finditer(text)]
    for m in _BARE_RE.finditer(text):
        if m.group(2).lower() in _TLDS:
            found.append(m.group(1))
    out, seen = [], set()
    for d in found:
        d = d.strip(".").lower()
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _is_official(domain: str, official: list[str]) -> bool:
    return any(domain == o or domain.endswith("." + o) for o in official)


def check_domain(domain: str, official: list[str]) -> dict:
    domain = domain.lower().strip(".")
    ascii_form = to_ascii(domain)
    flags: list[str] = []
    if _is_official(domain, official) and domain.isascii():
        return {"domain": domain, "ascii": ascii_form, "official": True, "flags": [], "closest": domain}
    if not domain.isascii() or (ascii_form and "xn--" in ascii_form):
        flags.append("punycode")
    skel = skeleton(domain)
    closest, best = None, 99
    for o in official:
        dist = levenshtein(skel, skeleton(o))
        if dist < best:
            closest, best = o, dist
        if skel == skeleton(o) or (0 < dist <= 2):
            flags.append(f"lookalike_of:{o} (distance {dist})")
        brand = o.split(".")[0]
        if len(brand) >= 4 and brand in skel and not _is_official(domain, official):
            flags.append(f"brand_token:{brand}")
    flags = list(dict.fromkeys(flags))
    return {"domain": domain, "ascii": ascii_form, "official": False, "flags": flags, "closest": closest}


def scan_text(text: str, official: list[str]) -> list[dict]:
    """Return only the suspicious domains found in text."""
    return [r for r in (check_domain(d, official) for d in extract_domains(text)) if r["flags"]]
