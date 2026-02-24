# doctor/views/visit.py
from __future__ import annotations

import json
import logging
import re
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from appointments.models import Appointment
from medical_archive.models import PatientArchive
from prescription.models import Prescription
from ..ai_rules import suggest_from_text

from .helpers import (
    AI_SUGGESTION_DISCLAIMER,
    _appt_select_related,
    _ensure_patient_template_attrs,
    _first_existing_field,
    _reverse_any,
    get_doctor_for_user,
    has_field,
    require_doctor_role,
)

logger = logging.getLogger(__name__)

# ✅ Diabetes ML (best-effort import)
try:
    from patient.services import predict_and_save as diabetes_predict_and_save  # type: ignore
except Exception:
    diabetes_predict_and_save = None  # type: ignore

try:
    from patient.services import quick_predict  # type: ignore
except Exception:
    quick_predict = None  # type: ignore


# ------------------------------------------------------------------
# Consultation / Visit (works with your doctor_visit.html)
# ------------------------------------------------------------------
class DoctorVisitForm(forms.Form):
    chief_complaint = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Headache, fever..."}),
    )
    symptoms = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Symptoms..."}),
    )
    history = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "History (optional)"}),
    )
    examination = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Examination (optional)"}),
    )
    preliminary_diagnosis = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Preliminary diagnosis"}),
    )
    final_diagnosis = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Final diagnosis"}),
    )
    plan = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Plan / Notes (optional)"}),
    )


# ------------------------------------------------------------------
# Session draft (prevents losing typed text when pressing Diabetes AI)
# ------------------------------------------------------------------
_DRAFT_SESSION_KEY_PREFIX = "doctor_visit_draft_appt_"
_DIABETES_FLASH_SESSION_KEY_PREFIX = "doctor_visit_diabetes_flash_appt_"


def _draft_key(appt_id: int) -> str:
    return f"{_DRAFT_SESSION_KEY_PREFIX}{appt_id}"


def _diabetes_flash_key(appt_id: int) -> str:
    return f"{_DIABETES_FLASH_SESSION_KEY_PREFIX}{appt_id}"


def _save_post_draft_to_session(request, appt_id: int) -> None:
    """
    Save the current form text to session to avoid losing it after redirect.
    Only store relevant fields.
    """
    try:
        data = {
            "chief_complaint": (request.POST.get("chief_complaint") or "").strip(),
            "symptoms": (request.POST.get("symptoms") or "").strip(),
            "history": (request.POST.get("history") or "").strip(),
            "examination": (request.POST.get("examination") or "").strip(),
            "preliminary_diagnosis": (request.POST.get("preliminary_diagnosis") or "").strip(),
            "final_diagnosis": (request.POST.get("final_diagnosis") or "").strip(),
            "plan": (request.POST.get("plan") or "").strip(),
            "_saved_at": timezone.now().isoformat(),
        }
        request.session[_draft_key(appt_id)] = data
        request.session.modified = True
    except Exception:
        # best-effort; do not break the flow
        logger.exception("Failed to save doctor visit draft to session (appt_id=%s)", appt_id)


def _pop_draft_from_session(request, appt_id: int) -> dict[str, Any]:
    """
    Pop draft from session (use once).
    """
    try:
        key = _draft_key(appt_id)
        draft = request.session.pop(key, None)
        if isinstance(draft, dict):
            return draft
        return {}
    except Exception:
        logger.exception("Failed to pop doctor visit draft from session (appt_id=%s)", appt_id)
        return {}


def _set_diabetes_flash(request, appt_id: int, payload: dict[str, Any]) -> None:
    try:
        request.session[_diabetes_flash_key(appt_id)] = _json_safe_payload(payload)
        request.session.modified = True
    except Exception:
        logger.exception("Failed to set diabetes flash in session (appt_id=%s)", appt_id)


def _pop_diabetes_flash(request, appt_id: int) -> dict[str, Any] | None:
    try:
        value = request.session.pop(_diabetes_flash_key(appt_id), None)
        return value if isinstance(value, dict) else None
    except Exception:
        logger.exception("Failed to pop diabetes flash from session (appt_id=%s)", appt_id)
        return None


# ------------------------------------------------------------------
# Diabetes UI mapping
# ------------------------------------------------------------------
def _diabetes_label_text(label: Any) -> str:
    try:
        v = int(label)
    except Exception:
        return str(label) if label is not None else ""
    return {
        0: str(_("Healthy")),
        1: str(_("Prediabetes")),
        2: str(_("Diabetes")),
    }.get(v, str(v))


def _risk_band_from_label(label: Any) -> str:
    try:
        v = int(label)
    except Exception:
        return ""
    return {0: "low", 1: "medium", 2: "high"}.get(v, "")


def _coerce_proba_dict(v: Any) -> dict[str, Any] | None:
    """
    Ensure proba is a dict (sometimes saved as JSON string).
    """
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _json_safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Make payload session-safe (JSON serializable).
    """
    out: dict[str, Any] = {}
    for k, v in payload.items():
        try:
            json.dumps(v)
            out[k] = v
        except Exception:
            out[k] = str(v)
    return out


# ------------------------------------------------------------------
# Diabetes AI helper (FAST)
# ------------------------------------------------------------------
def _run_diabetes_prediction_and_save(patient) -> tuple[dict[str, Any] | None, str | None]:
    """
    Runs diabetes prediction and saves to patient profile.
    Prefer patient.services.predict_and_save if available.
    Fallback: quick_predict + manual save.
    Returns payload ready for UI flash.
    """
    if patient is None:
        return None, "Patient is missing."

    # 1) Prefer predict_and_save (best)
    if diabetes_predict_and_save is not None:
        try:
            out = diabetes_predict_and_save(patient)

            label = None
            proba = None
            risk_band = None

            if isinstance(out, dict):
                label = out.get("label", None)
                proba = out.get("proba", None)
                risk_band = out.get("risk_band", None)
            else:
                label = out

            try:
                patient.refresh_from_db()
            except Exception:
                pass

            # pull saved fields (authoritative)
            if hasattr(patient, "diabetes_prediction"):
                try:
                    label = getattr(patient, "diabetes_prediction", label)
                except Exception:
                    pass

            if hasattr(patient, "prediction_proba"):
                try:
                    proba = getattr(patient, "prediction_proba", proba)
                except Exception:
                    pass

            proba = _coerce_proba_dict(proba)
            if not risk_band:
                risk_band = _risk_band_from_label(label)

            return {
                "label": label,
                "label_text": _diabetes_label_text(label),
                "risk_band": (risk_band or "").strip(),
                "proba": proba,
            }, None

        except Exception as e:
            logger.exception("Diabetes predict_and_save failed")
            return None, str(e)

    # 2) Fallback: quick_predict + manual save
    if quick_predict is None:
        return None, "Diabetes ML service is not available (imports failed)."

    try:
        result = quick_predict(patient) or {}
        label = result.get("label", None)
        proba = _coerce_proba_dict(result.get("proba", None))
        risk_band = (result.get("risk_band", "") or "").strip() or _risk_band_from_label(label)

        update_fields: list[str] = []

        if hasattr(patient, "diabetes_prediction"):
            patient.diabetes_prediction = int(label) if label is not None else None
            update_fields.append("diabetes_prediction")

        if hasattr(patient, "prediction_proba"):
            patient.prediction_proba = proba
            update_fields.append("prediction_proba")

        if update_fields:
            with transaction.atomic():
                try:
                    patient.save(skip_full_clean=True, update_fields=update_fields)  # type: ignore
                except TypeError:
                    patient.save(update_fields=update_fields)

        return {
            "label": label,
            "label_text": _diabetes_label_text(label),
            "risk_band": risk_band,
            "proba": proba,
        }, None

    except Exception as e:
        logger.exception("Diabetes quick_predict fallback failed")
        return None, str(e)


# ------------------------------------------------------------------
# AI helpers
# ------------------------------------------------------------------
def _doctor_specialty_label(doctor) -> str | None:
    if not doctor:
        return None

    try:
        v = getattr(doctor, "specialty", None)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if v:
            s = str(v).strip()
            if s:
                return s
    except Exception:
        pass

    try:
        sp = getattr(doctor, "specialty_profile", None)
        if sp:
            name = getattr(sp, "name", None)
            if isinstance(name, str) and name.strip():
                return name.strip()
            s = str(sp).strip()
            if s:
                return s
    except Exception:
        pass

    return None


def _ai_suggest(text: str, *, doctor=None):
    specialty = _doctor_specialty_label(doctor)
    try:
        return suggest_from_text(text, specialty=specialty)
    except Exception:
        logger.exception("AI suggestion failed")
        return {
            "suggested": "General assessment needed",
            "preliminary": "General assessment needed",
            "severity": "info",
            "source": "none",
            "items": (),
            "disclaimer": AI_SUGGESTION_DISCLAIMER,
        }


def _pick_from_s(s, key: str, default: str = "") -> str:
    try:
        v = s.get(key, None) if isinstance(s, dict) else getattr(s, key, None)
        v = "" if v is None else str(v)
        v = v.strip()
        return v or default
    except Exception:
        return default


def _normalize_severity(sev: str) -> str:
    s = (sev or "info").strip().lower()
    if s == "urgent":
        return "danger"
    if s not in ("danger", "warning", "info"):
        return "info"
    return s


def _build_ai_payload_from_s(s) -> dict[str, Any]:
    suggested = _pick_from_s(s, "suggested", "General assessment needed")
    preliminary = _pick_from_s(s, "preliminary", suggested or "General assessment needed")
    severity = _normalize_severity(_pick_from_s(s, "severity", "info"))
    source = _pick_from_s(s, "source", "none")
    disclaimer = _pick_from_s(s, "disclaimer", AI_SUGGESTION_DISCLAIMER) or AI_SUGGESTION_DISCLAIMER
    return {
        "suggested": suggested,
        "preliminary": preliminary,
        "severity": severity,
        "source": source,
        "disclaimer": disclaimer,
    }


def _suggestion_items_to_json(s) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    raw_items = getattr(s, "items", None) if not isinstance(s, dict) else s.get("items", None)

    if raw_items:
        for it in raw_items:
            items.append(
                {
                    "message": getattr(it, "message", "") if not isinstance(it, dict) else (it.get("message") or ""),
                    "severity": getattr(it, "severity", "info") if not isinstance(it, dict) else (it.get("severity") or "info"),
                    "source": getattr(it, "source", "none") if not isinstance(it, dict) else (it.get("source") or "none"),
                    "red_flag": bool(getattr(it, "red_flag", False) if not isinstance(it, dict) else it.get("red_flag", False)),
                }
            )

    if not items:
        base = _build_ai_payload_from_s(s)
        if base["suggested"]:
            items = [
                {
                    "message": base["suggested"],
                    "severity": base["severity"],
                    "source": base["source"],
                    "red_flag": False,
                }
            ]

    return items


def _extract_ai_payload(request) -> tuple[str, str, str, str] | None:
    try:
        if request.content_type and "application/json" in request.content_type.lower():
            body = (request.body or b"").decode("utf-8", errors="ignore") or "{}"
            payload = json.loads(body)
            if not isinstance(payload, dict):
                return None
            chief = (payload.get("chief_complaint") or "").strip()
            symptoms = (payload.get("symptoms") or "").strip()
            history = (payload.get("history") or "").strip()
            examination = (payload.get("examination") or "").strip()
        else:
            chief = (request.POST.get("chief_complaint") or "").strip()
            symptoms = (request.POST.get("symptoms") or "").strip()
            history = (request.POST.get("history") or "").strip()
            examination = (request.POST.get("examination") or "").strip()

        return chief, symptoms, history, examination
    except Exception:
        logger.exception("Failed to parse AI assist payload")
        return None


# ------------------------------------------------------------------
# Draft restore helpers (SAFE: restore only for the SAME appointment)
# ------------------------------------------------------------------
_SECTION_MAP = {
    "chief complaint": "chief_complaint",
    "symptoms": "symptoms",
    "history": "history",
    "examination": "examination",
    "preliminary dx": "preliminary_diagnosis",
    "preliminary diagnosis": "preliminary_diagnosis",
    "final dx": "final_diagnosis",
    "final diagnosis": "final_diagnosis",
    "plan": "plan",
    "plan / notes": "plan",
}


def _build_visit_notes(cd: dict[str, Any]) -> tuple[str, str]:
    blocks: list[str] = []

    if cd.get("chief_complaint"):
        blocks.append(f"Chief Complaint:\n{cd['chief_complaint']}")
    if cd.get("symptoms"):
        blocks.append(f"Symptoms:\n{cd['symptoms']}")
    if cd.get("history"):
        blocks.append(f"History:\n{cd['history']}")
    if cd.get("examination"):
        blocks.append(f"Examination:\n{cd['examination']}")
    if cd.get("preliminary_diagnosis"):
        blocks.append(f"Preliminary Dx:\n{cd['preliminary_diagnosis']}")
    if cd.get("final_diagnosis"):
        blocks.append(f"Final Dx:\n{cd['final_diagnosis']}")
    if cd.get("plan"):
        blocks.append(f"Plan:\n{cd['plan']}")

    full_notes = "\n\n".join([b for b in blocks if b]).strip()
    dx_value = (cd.get("final_diagnosis") or "").strip() or (cd.get("preliminary_diagnosis") or "").strip()
    return full_notes, dx_value


def _parse_visit_notes_to_initial(notes: str) -> dict[str, Any]:
    if not notes or not isinstance(notes, str):
        return {}

    initial: dict[str, Any] = {}
    chunks = [c.strip() for c in re.split(r"\n\s*\n", notes.strip()) if c.strip()]

    for chunk in chunks:
        lines = chunk.splitlines()
        if not lines:
            continue

        header = (lines[0] or "").strip()
        if not header.endswith(":"):
            continue

        header_key = header[:-1].strip().lower()
        field_name = _SECTION_MAP.get(header_key)
        if not field_name:
            continue

        value = "\n".join(lines[1:]).strip()
        if value:
            initial[field_name] = value

    return initial


def _get_latest_archive_for_same_appointment(*, appt, doctor, patient):
    if not has_field(PatientArchive, "appointment"):
        return None

    qs = PatientArchive.objects.filter(appointment=appt)

    if has_field(PatientArchive, "doctor"):
        qs = qs.filter(doctor=doctor)
    if has_field(PatientArchive, "patient") and patient is not None:
        qs = qs.filter(patient=patient)

    order_field = _first_existing_field(PatientArchive, ("updated_at", "modified_at", "created_at", "id")) or "id"
    try:
        return qs.order_by(f"-{order_field}").first()
    except Exception:
        logger.exception("Failed to load latest archive draft for appointment=%s", getattr(appt, "id", None))
        return None


def _safe_update_or_create_archive(*, lookup: dict[str, Any], defaults: dict[str, Any]):
    """
    Avoid MultipleObjectsReturned problems:
    - if one exists => update latest
    - else create

    NOTE:
    We intentionally re-raise unexpected exceptions so caller can show a clear
    error instead of silently creating duplicates.
    """
    with transaction.atomic():
        qs = PatientArchive.objects.filter(**lookup)
        obj = qs.order_by("-id").first()
        if obj:
            for k, v in defaults.items():
                setattr(obj, k, v)
            obj.save()
            return obj, False

        obj = PatientArchive.objects.create(**lookup, **defaults)
        return obj, True


def _archive_defaults_from_visit_data(*, title_field: str | None, diag_field: str | None, notes_field: str | None, dx_value: str, full_notes: str) -> dict[str, Any]:
    """
    Build defaults for archive save/update.
    Important: include empty strings for diagnosis/notes fields when present,
    so clearing text in UI also clears old stored values (no stale data).
    """
    defaults: dict[str, Any] = {}

    if title_field:
        defaults[title_field] = f"Visit - {timezone.localdate().isoformat()}"

    # ✅ Always set if field exists (even empty string) to avoid stale values.
    if diag_field:
        defaults[diag_field] = dx_value or ""

    if notes_field:
        defaults[notes_field] = full_notes or ""

    return defaults


def _render_doctor_visit_page(
    request,
    *,
    doctor,
    appt,
    patient,
    form,
    suggested,
    ai_items,
    ai_note,
    recent_archives,
    recent_prescriptions,
    diabetes_flash,
):
    return render(
        request,
        "doctor/doctor_visit.html",
        {
            "doctor": doctor,
            "appointment": appt,
            "patient": patient,
            "form": form,
            "suggested": suggested,
            "ai_items": ai_items,
            "ai_note": ai_note,
            "recent_archives": recent_archives,
            "recent_prescriptions": recent_prescriptions,
            "diabetes_flash": diabetes_flash,
        },
    )


# ------------------------------------------------------------------
# Views
# ------------------------------------------------------------------
@login_required
@require_doctor_role
def doctor_visit(request, appointment_id: int):
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        raise Http404(_("Doctor profile not found."))

    appt = get_object_or_404(
        _appt_select_related(Appointment.objects.all()),
        pk=appointment_id,
        doctor=doctor,  # ✅ owner isolation
    )

    patient = getattr(appt, "patient", None)
    _ensure_patient_template_attrs(patient)

    # Pop diabetes flash (show once) - scoped per appointment to avoid cross-tab mixups
    diabetes_flash = _pop_diabetes_flash(request, appt.id)

    # Recent archives (fail-closed if ownership cannot be constrained)
    recent_archives = PatientArchive.objects.none()
    if patient is not None and has_field(PatientArchive, "patient"):
        try:
            aq = PatientArchive.objects.filter(patient=patient)

            if has_field(PatientArchive, "doctor"):
                aq = aq.filter(doctor=doctor)
            else:
                # Fail-closed for multi-doctor privacy if archive has no doctor field.
                # (You can relax this later if tenant isolation guarantees exist elsewhere.)
                aq = PatientArchive.objects.none()

            if aq is not None and getattr(aq, "model", None) is PatientArchive:
                order_field = _first_existing_field(PatientArchive, ("created_at", "id")) or "id"
                recent_archives = aq.order_by(f"-{order_field}")[:5]
        except Exception:
            logger.exception("Failed to load recent archives (appt_id=%s)", appt.id)
            recent_archives = PatientArchive.objects.none()

    recent_prescriptions = Prescription.objects.none()
    try:
        if has_field(Prescription, "doctor"):
            pq = Prescription.objects.filter(doctor=doctor)
            if has_field(Prescription, "appointment"):
                pq = pq.filter(appointment__patient=patient) if patient is not None else pq
            elif has_field(Prescription, "patient"):
                pq = pq.filter(patient=patient) if patient is not None else pq
            order_field = _first_existing_field(Prescription, ("created_at", "issued_at", "date_issued", "id")) or "id"
            recent_prescriptions = pq.order_by(f"-{order_field}")[:5]
    except Exception:
        logger.exception("Failed to load recent prescriptions (appt_id=%s)", appt.id)
        recent_prescriptions = Prescription.objects.none()

    suggested: str | None = None
    ai_items: list[dict[str, Any]] = []
    ai_note: str = AI_SUGGESTION_DISCLAIMER

    title_field = _first_existing_field(PatientArchive, ("title", "subject", "name"))
    notes_field = _first_existing_field(PatientArchive, ("notes", "summary", "details", "content", "description"))
    diag_field = _first_existing_field(PatientArchive, ("diagnosis", "primary_diagnosis", "final_diagnosis", "assessment"))

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()

        # ✅ Diabetes AI (preserve typed notes)
        if action in {"predict_diabetes", "diabetes_ai", "run_diabetes"}:
            _save_post_draft_to_session(request, appt.id)

            if patient is None:
                messages.error(request, _("No patient attached to this appointment."))
                _set_diabetes_flash(request, appt.id, {"ok": False, "error": "No patient."})
                return redirect(request.path)

            payload, err = _run_diabetes_prediction_and_save(patient)
            if err:
                messages.error(request, _("Diabetes AI failed: %(err)s") % {"err": err})
                _set_diabetes_flash(request, appt.id, {"ok": False, "error": err})
            else:
                messages.success(
                    request,
                    _("✅ Diabetes AI saved: %(label)s (%(risk)s)")
                    % {"label": payload.get("label_text") if payload else "", "risk": (payload or {}).get("risk_band") or "n/a"},
                )
                _set_diabetes_flash(request, appt.id, {"ok": True, **(payload or {})})
            return redirect(request.path)

        form = DoctorVisitForm(request.POST)

        if action in {"", "save", "save_only"}:
            action = "save_only"

        if form.is_valid():
            cd = form.cleaned_data

            if action == "suggest":
                text_for_ai = "\n".join(
                    [
                        cd.get("chief_complaint") or "",
                        cd.get("symptoms") or "",
                        cd.get("history") or "",
                        cd.get("examination") or "",
                    ]
                ).strip()

                s = _ai_suggest(text_for_ai, doctor=doctor)
                base = _build_ai_payload_from_s(s)
                suggested = base["suggested"]
                ai_note = base["disclaimer"]
                ai_items = _suggestion_items_to_json(s)

                return _render_doctor_visit_page(
                    request,
                    doctor=doctor,
                    appt=appt,
                    patient=patient,
                    form=form,
                    suggested=suggested,
                    ai_items=ai_items,
                    ai_note=ai_note,
                    recent_archives=recent_archives,
                    recent_prescriptions=recent_prescriptions,
                    diabetes_flash=diabetes_flash,
                )

            full_notes, dx_value = _build_visit_notes(cd)

            lookup: dict[str, Any] = {}
            if has_field(PatientArchive, "appointment"):
                lookup["appointment"] = appt
            if has_field(PatientArchive, "doctor"):
                lookup["doctor"] = doctor
            if has_field(PatientArchive, "patient") and patient is not None:
                lookup["patient"] = patient

            defaults = _archive_defaults_from_visit_data(
                title_field=title_field,
                diag_field=diag_field,
                notes_field=notes_field,
                dx_value=dx_value,
                full_notes=full_notes,
            )

            try:
                if has_field(PatientArchive, "appointment") and lookup.get("appointment") is not None:
                    _, created = _safe_update_or_create_archive(lookup=lookup, defaults=defaults)
                    messages.success(request, _("Draft saved to archive.") if created else _("Draft updated in archive."))
                else:
                    create_kwargs: dict[str, Any] = {}

                    if has_field(PatientArchive, "doctor"):
                        create_kwargs["doctor"] = doctor
                    if has_field(PatientArchive, "patient") and patient is not None:
                        create_kwargs["patient"] = patient

                    # Keep same stale-data fix behavior when creating
                    if title_field:
                        create_kwargs[title_field] = defaults.get(title_field, f"Visit - {timezone.localdate().isoformat()}")
                    if diag_field:
                        create_kwargs[diag_field] = defaults.get(diag_field, "")
                    if notes_field:
                        create_kwargs[notes_field] = defaults.get(notes_field, "")

                    PatientArchive.objects.create(**create_kwargs)
                    messages.success(request, _("Visit saved successfully."))

            except Exception:
                logger.exception(
                    "Failed saving doctor visit to archive (appt_id=%s, doctor_id=%s)",
                    appt.id,
                    getattr(doctor, "id", None),
                )
                messages.error(request, _("Could not save the visit. Please check archive fields."))
                return _render_doctor_visit_page(
                    request,
                    doctor=doctor,
                    appt=appt,
                    patient=patient,
                    form=form,
                    suggested=suggested,
                    ai_items=ai_items,
                    ai_note=ai_note,
                    recent_archives=recent_archives,
                    recent_prescriptions=recent_prescriptions,
                    diabetes_flash=diabetes_flash,
                )

            if action == "save_and_prescribe":
                for name in ("prescription:create", "prescription:create_prescription", "prescription:create_for_appointment"):
                    try:
                        return redirect(name, appt.id)
                    except Exception:
                        continue
                return redirect(_reverse_any("doctor:dashboard"))

            return redirect(request.path)

        messages.error(request, _("Please correct the errors in the form."))

    else:
        initial: dict[str, Any] = {}

        # 1) Restore draft from session first (if doctor pressed Diabetes AI)
        session_draft = _pop_draft_from_session(request, appt.id)
        if session_draft:
            session_draft.pop("_saved_at", None)
            initial.update({k: v for k, v in session_draft.items() if isinstance(v, str) and v.strip()})

        # 2) Then restore latest archive draft (only fill missing fields)
        draft_obj = _get_latest_archive_for_same_appointment(appt=appt, doctor=doctor, patient=patient)
        if draft_obj is not None and notes_field and has_field(PatientArchive, notes_field):
            try:
                draft_notes = getattr(draft_obj, notes_field, "") or ""
                parsed = _parse_visit_notes_to_initial(draft_notes)
                for k, v in parsed.items():
                    initial.setdefault(k, v)
            except Exception:
                logger.exception("Failed parsing archive draft notes (appt_id=%s)", appt.id)

        # ✅ Fixed bug:
        # check missing preliminary_diagnosis before filling preliminary_diagnosis
        try:
            if draft_obj is not None and diag_field and has_field(PatientArchive, diag_field):
                dx = (getattr(draft_obj, diag_field, "") or "").strip()
                if dx and "preliminary_diagnosis" not in initial:
                    initial.setdefault("preliminary_diagnosis", dx)
        except Exception:
            logger.exception("Failed restoring diagnosis from archive draft (appt_id=%s)", appt.id)

        form = DoctorVisitForm(initial=initial)

    return _render_doctor_visit_page(
        request,
        doctor=doctor,
        appt=appt,
        patient=patient,
        form=form,
        suggested=suggested,
        ai_items=ai_items,
        ai_note=ai_note,
        recent_archives=recent_archives,
        recent_prescriptions=recent_prescriptions,
        diabetes_flash=diabetes_flash,
    )


@login_required
@require_doctor_role
@require_POST
def visit_ai_assist(request, appointment_id: int):
    """
    AJAX endpoint for AI Assist on doctor_visit.html.
    """
    doctor = get_doctor_for_user(request.user)
    if not doctor:
        return JsonResponse({"ok": False, "error": "Doctor profile not found."}, status=404)

    appt = get_object_or_404(
        Appointment.objects.select_related("patient", "doctor"),
        pk=appointment_id,
        doctor=doctor,  # ✅ owner isolation
    )

    parsed = _extract_ai_payload(request)
    if not parsed:
        return JsonResponse({"ok": False, "error": "Invalid request body."}, status=400)

    chief, symptoms, history, examination = parsed
    if not chief or not symptoms:
        return JsonResponse({"ok": False, "error": "Chief Complaint and Symptoms are required."}, status=400)

    text_for_ai = "\n".join([chief, symptoms, history, examination]).strip()

    s = _ai_suggest(text_for_ai, doctor=doctor)
    base = _build_ai_payload_from_s(s)
    items = _suggestion_items_to_json(s)

    return JsonResponse(
        {
            "ok": True,
            "appointment_id": appt.id,
            "suggested": base["suggested"],
            "preliminary": base["preliminary"],
            "severity": base["severity"],
            "source": base["source"],
            "count": len(items),
            "items": items,
            "ai_note": base["disclaimer"],
            "disclaimer": base["disclaimer"],
        }
    )