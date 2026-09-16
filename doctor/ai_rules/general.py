from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Literal
import re


Severity = Literal["info", "warning", "danger"]


@dataclass(frozen=True)
class Rule:
    keywords: tuple[str, ...]
    suggestion: str
    severity: Severity = "info"
    red_flag: bool = False


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\u0600-\u06FF]+", re.UNICODE)

# Allow negation to cover lists like: "No shortness of breath/wheezing"
_NEG_WINDOW_WORDS = 6


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return f" {t} "


def _latin_word_match(t: str, word: str) -> bool:
    w = re.escape(word.lower())
    return re.search(rf"(?<![a-z0-9]){w}(?![a-z0-9])", t) is not None


_NEG_EN = (
    "no", "without", "denies", "denied", "negative for", "neg for",
    "absence of", "absent", "not present", "ruled out"
)
_NEG_AR = ("لا", "بدون", "ماكو", "ليس", "مو", "غير", "ينفي", "لا يوجد", "لايوجد", "غير موجود")


def _kw_pattern(keyword: str) -> str:
    kw = (keyword or "").strip().lower().replace("-", " ")
    kw = _PUNCT_RE.sub(" ", kw)
    kw = _WS_RE.sub(" ", kw).strip()
    parts = [re.escape(p) for p in kw.split() if p]
    if not parts:
        return ""
    return r"\s+".join(parts)


def _is_negated(t_norm: str, keyword: str) -> bool:
    pat = _kw_pattern(keyword)
    if not pat:
        return False

    neg_en = r"|".join(re.escape(w) for w in _NEG_EN)
    neg_ar = r"|".join(re.escape(w) for w in _NEG_AR)

    rx1 = re.compile(
        rf"(?:^|\s)(?:{neg_en}|{neg_ar})\s+(?:\w+\s+){{0,{_NEG_WINDOW_WORDS}}}{pat}(?:\s|$)"
    )
    if rx1.search(t_norm):
        return True

    rx2 = re.compile(
        rf"(?:^|\s){pat}\s+(?:\w+\s+){{0,{_NEG_WINDOW_WORDS}}}"
        rf"(?:absent|negative|not present|ruled out|غير موجود)(?:\s|$)"
    )
    if rx2.search(t_norm):
        return True

    return False


def _keyword_present(t_norm: str, keyword: str) -> bool:
    k = (keyword or "").strip().lower()
    if not k:
        return False

    k = _PUNCT_RE.sub(" ", k.replace("-", " "))
    k = _WS_RE.sub(" ", k).strip()
    if not k:
        return False

    if " " in k:
        return f" {k} " in t_norm

    if re.fullmatch(r"[a-z0-9]+", k):
        return _latin_word_match(t_norm, k)

    return (f" {k} " in t_norm) or (k in t_norm)


def _contains_any_positive(t_norm: str, keys: Iterable[str]) -> bool:
    """
    Match only if keyword is present AND NOT negated.
    """
    for k in keys:
        if _keyword_present(t_norm, k) and not _is_negated(t_norm, k):
            return True
    return False


_SEV_RANK = {"danger": 0, "urgent": 0, "warning": 1, "info": 2}


GENERAL_RULES: List[Rule] = [
    Rule(
        keywords=(
            "chest pain", "shortness of breath", "sob", "difficulty breathing",
            "ألم بالصدر", "الم بالصدر", "ضيق نفس", "صعوبة تنفس", "نهجان",
        ),
        suggestion="Possible urgent cardio-respiratory concern — urgent clinical evaluation is recommended.",
        severity="danger",
        red_flag=True,
    ),
    Rule(
        keywords=(
            "severe bleeding", "loss of consciousness", "stroke",
            "نزيف شديد", "فقدان الوعي", "اغماء", "جلطة", "سكتة"
        ),
        suggestion="Red-flag symptoms — urgent emergency assessment is recommended.",
        severity="danger",
        red_flag=True,
    ),

    # Fever/temperature -> Warning (stronger infection indicator)
    Rule(
        keywords=("fever", "temperature", "حمى", "حرارة"),
        suggestion="Suspected infection / febrile illness — consider evaluation and vital signs monitoring.",
        severity="warning",
    ),

    # Chills alone -> Info (do not over-warn if no documented fever)
    Rule(
        keywords=("chills", "rigors", "قشعريرة", "رجفة"),
        suggestion="Chills reported — consider checking temperature and monitoring vital signs if symptoms persist or worsen.",
        severity="info",
    ),

    Rule(
        keywords=("cough", "sore throat", "runny nose", "سعال", "كحة", "التهاب حلق", "احتقان", "رشح", "زكام"),
        suggestion="Upper respiratory symptoms — consider respiratory assessment and supportive care if appropriate.",
        severity="info",
    ),
    Rule(
        keywords=("abdominal pain", "vomiting", "nausea", "ألم بطن", "الم بطن", "تقيؤ", "قيء", "غثيان"),
        suggestion="Gastrointestinal complaint — consider hydration status and clinical evaluation.",
        severity="info",
    ),
    Rule(
        keywords=("headache", "migraine", "photophobia", "صداع", "شقيقة", "حساسية للضوء", "رهاب الضوء"),
        suggestion="Headache pattern — consider neurological assessment if severe or atypical.",
        severity="info",
    ),
    Rule(
        keywords=(
            "polyuria", "polydipsia", "weight loss", "excessive thirst",
            "كثرة التبول", "عطش شديد", "نقص وزن", "جوع شديد"
        ),
        suggestion="Possible diabetes symptoms — consider checking glucose / HbA1c.",
        severity="info",
    ),

    # ------------------------------------------------------------
    # Breast pain (mastalgia) and breast red flags
    # ------------------------------------------------------------
    Rule(
        keywords=(
            "breast pain", "mastalgia", "breast tenderness", "sore breast",
            "ألم بالثدي", "الم بالثدي", "وجع الثدي", "ألم الثدي", "تحسس الثدي",
        ),
        suggestion=(
            "Breast pain (mastalgia) — consider breast exam and supportive care. "
            "If persistent or associated with red flags (new lump, nipple discharge, skin changes), "
            "consider prompt evaluation and breast ultrasound."
        ),
        severity="info",
    ),
    Rule(
        keywords=(
            "breast lump", "new lump", "nipple discharge", "bloody discharge",
            "skin dimpling", "peau d orange", "inverted nipple",
            "كتلة بالثدي", "ورم بالثدي", "افرازات من الحلمة", "إفرازات من الحلمة",
            "إفرازات دموية", "تغير جلد الثدي", "تراجع الحلمة",
        ),
        suggestion=(
            "Breast red-flag features — prompt clinical assessment is recommended; "
            "consider imaging (ultrasound/mammography as appropriate)."
        ),
        severity="warning",
        red_flag=True,
    ),
]


def suggest_all(text: str) -> list[Rule]:
    t = _norm(text)
    matches: list[Rule] = []
    seen: set[str] = set()

    for r in GENERAL_RULES:
        if _contains_any_positive(t, r.keywords):
            if r.suggestion in seen:
                continue
            matches.append(r)
            seen.add(r.suggestion)

    matches.sort(key=lambda x: _SEV_RANK.get((x.severity or "info").lower(), 9))
    return matches


def suggest(text: str) -> Rule | None:
    all_rules = suggest_all(text)
    return all_rules[0] if all_rules else None
