"""PDF forensics (SPEC §9.1): find text a human cannot see but a model would read.

Flags characters with near-white fill, font size < 2pt, or a position outside the page box;
also scans annotations and metadata. Returns the hidden spans WITH their text so the UI can
reveal them, plus the visible text (hidden spans removed) for the quarantined extractor.
"""
from __future__ import annotations

import io
from typing import Any

import pdfplumber

from . import injection

WHITE_THRESHOLD = 0.9
TINY_FONT_PT = 2.0


def _near_white(color: Any) -> bool:
    if color is None or isinstance(color, str):
        return False
    try:
        vals = [float(v) for v in (color if isinstance(color, (list, tuple)) else [color])]
    except (TypeError, ValueError):
        return False
    if len(vals) == 1:  # gray
        return vals[0] >= WHITE_THRESHOLD
    if len(vals) == 3:  # RGB
        return all(v >= WHITE_THRESHOLD for v in vals)
    if len(vals) == 4:  # CMYK: white is no ink
        return all(v <= 1 - WHITE_THRESHOLD for v in vals)
    return False


def _hidden_reasons(ch: dict, width: float, height: float) -> list[str]:
    reasons = []
    if _near_white(ch.get("non_stroking_color")):
        reasons.append("white")
    if float(ch.get("size", 12)) < TINY_FONT_PT:
        reasons.append("tiny")
    if ch["x1"] < 0 or ch["x0"] > width or ch["bottom"] < 0 or ch["top"] > height:
        reasons.append("offpage")
    return reasons


def _is_rotated(ch: dict) -> bool:
    m = ch.get("matrix") or (1, 0, 0, 1, 0, 0)
    return abs(float(m[1])) > 0.01 or abs(float(m[2])) > 0.01


def _describe(reasons: set[str], size: float, color: Any) -> str:
    parts = []
    if "white" in reasons:
        parts.append("white")
    if "tiny" in reasons or size < 4:
        parts.append(f"{size:g}pt")
    if "offpage" in reasons:
        parts.append("outside the page")
    return ", ".join(parts) or "hidden"


def analyze_pdf(data: bytes) -> dict:
    hidden_spans: list[dict] = []
    visible_pages: list[str] = []
    annotations: list[dict] = []
    metadata_flags: list[dict] = []
    rotated_pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for meta_key, meta_val in (pdf.metadata or {}).items():
            if isinstance(meta_val, str) and meta_val.strip():
                hits = injection.scan(meta_val)
                if hits["injection_hits"]:
                    metadata_flags.append({"key": meta_key, "text": meta_val})
                    hidden_spans.append({"page": 0, "text": meta_val, "reasons": ["metadata"],
                                         "description": f"PDF metadata field {meta_key}"})
        for pno, page in enumerate(pdf.pages, 1):
            w, h = float(page.width), float(page.height)
            span: dict | None = None
            last_top = None
            for ch in page.chars:
                reasons = _hidden_reasons(ch, w, h)
                if reasons:
                    if span is not None and set(reasons) != span["key"]:
                        _emit(hidden_spans, span)  # a different kind of hiding starts a new span
                        span, last_top = None, None
                    if span is None:
                        span = {"page": pno, "chars": [], "reasons": set(), "key": set(reasons),
                                "size": float(ch.get("size", 0)), "color": ch.get("non_stroking_color")}
                    if last_top is not None and abs(ch["top"] - last_top) > 1 and span["chars"]:
                        span["chars"].append(" ")
                    span["chars"].append(ch["text"])
                    span["reasons"].update(reasons)
                    span["size"] = min(span["size"], float(ch.get("size", 0)))
                    last_top = ch["top"]
                elif span is not None and ch["text"].strip():
                    _emit(hidden_spans, span)
                    span, last_top = None, None
            if span is not None:
                _emit(hidden_spans, span)
            # Rotated text (e.g. the SANDBOX SAMPLE watermark) is kept out of the extractor's input
            # but still scanned by the detectors.
            rotated = "".join(ch["text"] for ch in page.chars if _is_rotated(ch) and not _hidden_reasons(ch, w, h))
            if rotated.strip():
                rotated_pages.append(rotated)
            visible = page.filter(lambda o: o.get("object_type") != "char"
                                  or (not _is_rotated(o) and not _hidden_reasons(o, w, h)))
            visible_pages.append(visible.extract_text() or "")
            for annot in page.annots or []:
                contents = (annot.get("contents") or "").strip()
                if contents:
                    annotations.append({"page": pno, "text": contents})
                    hidden_spans.append({"page": pno, "text": contents, "reasons": ["annotation"],
                                         "description": "PDF annotation (not part of the printed page)"})
    return {
        "visible_text": "\n".join(visible_pages),
        "hidden_spans": hidden_spans,
        "annotations": annotations,
        "metadata_flags": metadata_flags,
        "rotated_text": "\n".join(rotated_pages),
    }


def _emit(out: list[dict], span: dict) -> None:
    closed = _close(span)
    if closed["text"]:
        out.append(closed)


def _close(span: dict) -> dict:
    text = " ".join("".join(span["chars"]).split())
    reasons = sorted(span["reasons"])
    return {
        "page": span["page"],
        "text": text,
        "reasons": reasons,
        "font_size": round(span["size"], 2),
        "description": _describe(set(reasons), span["size"], span["color"]),
    }
