from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Literal
import re


Severity = Literal["info", "warning", "danger"]


@dataclass(frozen=True)
class Rule:
    keywords_any: tuple[str, ...]
    suggestion: str
    severity: Severity = "info"
    red_flag: bool = False
    tag: str = ""  # used for special handling


# -----------------------------
# Text normalization + matching
# -----------------------------
_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\u0600-\u06FF]+", re.UNICODE)  # keep Arabic letters too


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return f" {t} "


def _latin_word_match(t: str, word: str) -> bool:
    w = re.escape(word.lower())
    return re.search(rf"(?<![a-z0-9]){w}(?![a-z0-9])", t) is not None


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


# -----------------------------
# Negation handling (IMPORTANT)
# -----------------------------
_NEG_EN = (
    "no", "without", "denies", "denied", "negative for", "neg for",
    "absence of", "absent", "not present", "ruled out"
)

_NEG_AR = (
    "لا", "بدون", "ماكو", "ليس", "مو", "غير",
    "ينفي", "لا يوجد", "لايوجد", "غير موجود"
)

# Allow negation to cover short enumerations:
# "No shortness of breath/wheezing"
# After normalization => "no shortness of breath wheezing"
_NEG_WINDOW_WORDS = 6


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


def _any_positive_keyword(t_norm: str, keys: Iterable[str]) -> bool:
    """
    True if ANY keyword is present AND NOT negated.
    Prevents false positives like:
      "No lip swelling" triggering angioedema.
    """
    for k in keys:
        if _keyword_present(t_norm, k) and not _is_negated(t_norm, k):
            return True
    return False


# -----------------------------
# Special detectors
# -----------------------------
_EMERG_STRONG = (
    "stevens johnson", "sjs", "ten", "toxic epidermal necrolysis",
    "target lesions", "peeling skin",
    "تسلخ", "تقشر شديد"
)

_EMERG_WEAK = (
    "mucosal", "oral ulcers", "eye pain", "bullae", "blister", "blisters", "blistering rash",
    "تقرحات", "تقرح", "فقاعات", "حويصلات", "حرقان العين"
)


def _emergency_should_fire(t_norm: str) -> bool:
    for k in _EMERG_STRONG:
        if _keyword_present(t_norm, k) and not _is_negated(t_norm, k):
            return True
    return _any_positive_keyword(t_norm, _EMERG_WEAK)


# -----------------------------
# CTCL / Sézary scoring (bucketed to reduce double counting)
# -----------------------------
_CTCL_BUCKETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("erythema", ("erythroderma", "generalized erythema", "diffuse erythema", "احمرار منتشر")),
    ("pruritus", ("severe pruritus", "pruritus", "itching", "حكة شديدة", "حكة", "حكه")),
    ("weight_loss", ("weight loss", "نقص وزن")),
    ("night_sweats", ("night sweats", "تعرق ليلي")),
    ("lymph_nodes", ("lymphadenopathy", "enlarged lymph nodes", "تضخم عقد", "تضخم عقدة", "تضخم العقد")),
    ("ctcl_terms", ("sezary", "ctcl", "mycosis fungoides")),
    ("labs", ("eosinophilia", "elevated ldh", "ldh elevated", "ldh مرتفع", "ارتفاع ldh")),
)


def _ctcl_bucket_hits(t_norm: str) -> dict[str, bool]:
    hits: dict[str, bool] = {}
    for bucket, keys in _CTCL_BUCKETS:
        hits[bucket] = _any_positive_keyword(t_norm, keys)
    return hits


def _ctcl_should_warn(t_norm: str) -> bool:
    """
    More conservative trigger to avoid over-alarming:
      - score >= 4
      OR score >= 3 AND (lymph_nodes OR night_sweats)
      OR ctcl_terms present AND (score >= 3)  (explicit CTCL mention)
    """
    hits = _ctcl_bucket_hits(t_norm)
    score = sum(1 for v in hits.values() if v)

    systemic_strong = bool(hits.get("lymph_nodes")) or bool(hits.get("night_sweats"))
    ctcl_terms = bool(hits.get("ctcl_terms"))

    if score >= 4:
        return True
    if score >= 3 and systemic_strong:
        return True
    if ctcl_terms and score >= 3:
        return True
    return False


# -----------------------------
# Infection gating (reduce false positives)
# -----------------------------
_BACTERIAL_STRONG = (
    "cellulitis", "abscess", "pus", "warmth", "rapidly spreading", "fever",
    "التهاب نسيج خلوي", "خراج", "قيح", "سخونة", "انتشار سريع", "حرارة"
)


# -----------------------------
# Rules
# -----------------------------
DERM_RULES: List[Rule] = [
    # --- RED FLAGS (danger) ---
    Rule(
        keywords_any=(
            "stevens johnson", "sjs", "ten", "toxic epidermal necrolysis",
            "mucosal", "oral ulcers", "eye pain", "peeling skin",
            "target lesions", "bullae", "blistering rash", "blister", "blisters",
            "تقرحات", "تقرح", "تسلخ", "تقشر شديد", "فقاعات", "حويصلات", "حرقان العين"
        ),
        suggestion=(
            "⚠️ Skin emergency pattern (severe blistering / mucosal involvement) — "
            "urgent medical evaluation is recommended."
        ),
        severity="danger",
        red_flag=True,
        tag="sjs_ten_redflag",
    ),
    Rule(
        keywords_any=(
            "difficulty breathing", "shortness of breath", "wheezing", "throat swelling",
            "tongue swelling", "lip swelling", "facial swelling", "angioedema",
            "ضيق نفس", "صعوبة تنفس", "صفير", "تورم الحلق", "تورم اللسان", "تورم الشفاه", "تورم الوجه", "اختناق"
        ),
        suggestion="⚠️ Possible severe allergic reaction/angioedema — urgent assessment is recommended.",
        severity="danger",
        red_flag=True,
        tag="angioedema_redflag",
    ),

    # --- Common dermatology patterns ---
    Rule(
        keywords_any=("ringworm", "tinea", "annular", "ring shaped", "central clearing",
                      "فطريات", "تينيا", "سعفة", "سعفه", "قوباء حلقية"),
        suggestion=(
            "May be consistent with a fungal skin infection (tinea) — consider clinical evaluation "
            "and appropriate antifungal management if confirmed."
        ),
        severity="info",
        tag="tinea",
    ),

    # ✅ UPDATED: Urticaria should NOT trigger on "itching" alone.
    # It will trigger only when hives/urticaria/wheals are mentioned.
    Rule(
        keywords_any=(
            "hives", "hive", "urticaria", "urticarial", "wheals", "welts",
            "شرى", "أرتيكاريا", "ارتيكاريا"
        ),
        suggestion=(
            "May be consistent with urticaria/allergic reaction — consider trigger assessment and symptom relief "
            "based on clinician judgment."
        ),
        severity="warning",
        tag="urticaria",
    ),

    Rule(
        keywords_any=("eczema", "dermatitis", "dry skin", "atopic",
                      "اكزيما", "إكزيما", "التهاب جلد", "جفاف الجلد", "تحسس جلدي"),
        suggestion=(
            "May be consistent with dermatitis/eczema — consider moisturization, trigger avoidance, "
            "and clinical evaluation."
        ),
        severity="info",
        tag="eczema",
    ),
    Rule(
        keywords_any=("acne", "pimples", "comedones",
                      "حب الشباب", "حَبّ الشباب", "بثور", "رؤوس سوداء", "رؤوس بيضاء"),
        suggestion="May be consistent with acneiform eruption — consider an acne management approach clinically.",
        severity="info",
        tag="acne",
    ),
    Rule(
        keywords_any=(
            # strong indicators
            "cellulitis", "abscess", "pus", "warmth", "rapidly spreading", "fever",
            "التهاب نسيج خلوي", "خراج", "قيح", "سخونة", "انتشار سريع", "حرارة",
            # weak (kept but gated)
            "redness", "swelling", "تورم", "احمرار"
        ),
        suggestion=(
            "May be consistent with bacterial skin infection — consider clinical assessment; "
            "urgent evaluation if systemic symptoms or rapid progression."
        ),
        severity="warning",
        tag="bacterial_infection",
    ),
]


# -----------------------------
# Public API
# -----------------------------
def suggest_all(text: str) -> list[Rule]:
    """
    Return ALL matching rules, ordered by severity (danger -> warning -> info),
    then by rule order in the list.
    """
    t = _norm(text)
    matches: list[Rule] = []

    for r in DERM_RULES:
        if not _any_positive_keyword(t, r.keywords_any):
            continue

        if r.tag == "sjs_ten_redflag":
            if not _emergency_should_fire(t):
                continue

        if r.tag == "angioedema_redflag":
            if not _any_positive_keyword(t, r.keywords_any):
                continue

        if r.tag == "bacterial_infection":
            # Require at least one strong indicator to avoid warnings from mere "redness"
            if not _any_positive_keyword(t, _BACTERIAL_STRONG):
                continue

        matches.append(r)

    # Add CTCL/Sézary consideration only when conservative criteria met
    if _ctcl_should_warn(t):
        matches.append(
            Rule(
                keywords_any=(),
                suggestion=(
                    "Erythroderma with severe pruritus plus systemic features may raise concern for cutaneous T-cell lymphoma (CTCL), "
                    "including Sézary syndrome. Consider dermatology evaluation and (if clinically indicated) multiple skin biopsies "
                    "(different sites), CBC with smear, LDH, flow cytometry, and TCR studies."
                ),
                severity="warning",
                red_flag=False,
                tag="ctcl_warning",
            )
        )

    sev_rank = {"danger": 0, "warning": 1, "info": 2}
    matches.sort(key=lambda r: sev_rank.get(r.severity, 9))
    return matches


def suggest(text: str) -> Rule | None:
    matches = suggest_all(text)
    return matches[0] if matches else None
