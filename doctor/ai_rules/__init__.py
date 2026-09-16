# doctor/ai_rules/__init__.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import dermatology as derm_pack
from . import general as general_pack


AI_SUGGESTION_DISCLAIMER = "AI suggestion (rule-based). Clinician must confirm."

# Lower number = higher priority
_SEV_RANK = {"danger": 0, "urgent": 0, "warning": 1, "info": 2}


def _norm_severity(sev: str) -> str:
    s = (sev or "info").strip().lower()
    # keep backward compatibility
    if s == "urgent":
        return "danger"
    if s not in ("danger", "warning", "info"):
        return "info"
    return s


@dataclass(frozen=True)
class SuggestionItem:
    message: str
    severity: str  # info | warning | danger
    source: str    # general | dermatology
    red_flag: bool = False


@dataclass(frozen=True)
class Suggestion:
    """
    A lightweight suggestion payload returned by the rule router.
    NOT a diagnosis.
    """
    suggested: str
    preliminary: str
    severity: str
    source: str
    items: tuple[SuggestionItem, ...] = ()
    disclaimer: str = AI_SUGGESTION_DISCLAIMER


# ✅ IMPORTANT:
# This list decides when we should run dermatology rules even if specialty is unknown.
# We must include blistering/mucosal/Nikolsky/etc or SJS/TEN cases will fall back to GENERAL only.
_DERM_HINTS = (
    # ----------------
    # EN (Derm keywords)
    # ----------------
    "skin", "rash", "eruption", "pruritus", "itch", "itching",
    "eczema", "dermatitis", "atopic", "psoriasis", "scaly", "scales",
    "tinea", "ringworm", "fungal", "annular", "central clearing",
    "acne", "comedones", "pimples",
    "urticaria", "hives", "angioedema",
    "cellulitis", "abscess", "pus",
    # blistering / mucosal
    "blister", "blisters", "bullae", "bulla", "vesicle", "vesicles",
    "erosion", "erosions", "ulcer", "ulcers",
    "mucosal", "oral ulcers", "mouth sores", "conjunctival", "eye pain",
    "nikolsky", "peeling skin", "target lesions",
    # SJS/TEN explicit
    "stevens johnson", "sjs", "ten", "toxic epidermal necrolysis",
    # erythroderma / CTCL hints
    "erythroderma", "diffuse erythema", "generalized erythema",

    # ----------------
    # AR (Derm keywords)
    # ----------------
    "جلد", "جلدية", "طفح", "تحسس", "حساسية", "احمرار",
    "حكة", "حكه", "حرقان", "قشور", "تقشر", "تسلخ",
    "اكزيما", "إكزيما", "التهاب جلد",
    "فطريات", "تينيا", "سعفة", "سعفه",
    "حب الشباب", "بثور", "رؤوس سوداء", "رؤوس بيضاء",
    "شرى", "أرتيكاريا", "وذمة", "تورم",
    "التهاب نسيج خلوي", "خراج", "قيح",
    # blistering / mucosal
    "فقاعات", "حويصلات", "بثور مائية", "تقرحات", "تقرح",
    "تقرحات الفم", "تقرحات فموية", "حرقان العين",
    "علامة نيكولسكي", "نيكولسكي",
)


def _pick_suggest(mod: Any) -> Optional[Callable[[str], object | None]]:
    """
    Pick a callable suggestion function from a rules pack module.
    Prefer suggest_all (for multiple findings) then suggest.
    """
    candidate_names = ("suggest_all", "suggest", "suggest_from_text", "route", "predict")
    for name in candidate_names:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


def _collect(mod: Any, src: str, text: str) -> list[SuggestionItem]:
    """
    Collect rules from a module:
    - if suggest_all exists: returns many
    - else suggest returns one
    """
    fn_all = getattr(mod, "suggest_all", None)
    if callable(fn_all):
        rules = fn_all(text) or []
        items: list[SuggestionItem] = []
        for r in rules:
            msg = getattr(r, "suggestion", "") or ""
            if not msg:
                continue
            items.append(
                SuggestionItem(
                    message=msg,
                    severity=_norm_severity(getattr(r, "severity", "info")),
                    source=src,
                    red_flag=bool(getattr(r, "red_flag", False)),
                )
            )
        return items

    fn = _pick_suggest(mod)
    if not callable(fn):
        return []

    r = fn(text)
    if not r:
        return []

    msg = getattr(r, "suggestion", "") or ""
    if not msg:
        return []

    return [
        SuggestionItem(
            message=msg,
            severity=_norm_severity(getattr(r, "severity", "info")),
            source=src,
            red_flag=bool(getattr(r, "red_flag", False)),
        )
    ]


def _is_derm_specialty(spec: str) -> bool:
    s = (spec or "").strip().lower()
    return ("derm" in s) or ("skin" in s) or ("جلدية" in s) or ("جلد" in s)


def _text_has_derm_hints(text: str) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in _DERM_HINTS)


def _dedupe(items: list[SuggestionItem]) -> list[SuggestionItem]:
    seen: set[str] = set()
    out: list[SuggestionItem] = []
    for it in items:
        key = (it.message or "").strip()
        if not key or key in seen:
            continue
        out.append(it)
        seen.add(key)
    return out


def suggest_from_text(text: str, specialty: str | None = None) -> Suggestion:
    """
    ✅ Behavior:
    - Always collect GENERAL items.
    - Collect DERM items ONLY if:
        a) doctor specialty is dermatology/skin
        OR
        b) the text contains clear derm hints (including blisters/mucosal/Nikolsky/SJS/TEN keywords)

    This prevents dermatology rules from appearing in non-derm complaints
    unless the complaint actually looks dermatologic.
    """
    t = (text or "").strip()
    spec = (specialty or "").strip()

    include_derm = _is_derm_specialty(spec) or _text_has_derm_hints(t)

    general_items = _collect(general_pack, "general", t)
    derm_items = _collect(derm_pack, "dermatology", t) if include_derm else []

    # Merge
    items = _dedupe(general_items + derm_items)

    # Sort: severity first, then red_flag first
    items.sort(key=lambda x: (_SEV_RANK.get(x.severity, 9), 0 if x.red_flag else 1))

    if items:
        top = items[0]
        # stable unique order in source string
        src = "+".join(dict.fromkeys([i.source for i in items]))
        return Suggestion(
            suggested=top.message,
            preliminary=top.message,
            severity=top.severity,
            source=src,
            items=tuple(items),
        )

    fallback = "General assessment needed"
    return Suggestion(
        suggested=fallback,
        preliminary=fallback,
        severity="info",
        source="none",
        items=(),
    )


__all__ = ["Suggestion", "SuggestionItem", "suggest_from_text", "AI_SUGGESTION_DISCLAIMER"]
