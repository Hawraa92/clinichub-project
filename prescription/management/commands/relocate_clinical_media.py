from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from core.private_storage import private_clinical_storage
from doctor.models import Doctor
from lab.models import LabOrder, LabResult
from prescription.models import Prescription


FIELD_SPECS = (
    (Prescription, "pdf_file"),
    (Prescription, "voice_note"),
    (Prescription, "doctor_signature"),
    (Prescription, "qr_code"),
    (LabOrder, "doctor_attachment"),
    (LabResult, "attachment"),
    (Doctor, "signature_image"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Report or safely copy allowlisted clinical media into private storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Copy verified files; without this flag the command is report-only.",
        )
        parser.add_argument(
            "--manifest",
            help="Write the JSON manifest to this explicit path.",
        )

    def handle(self, *args, **options):
        execute = bool(options["execute"])
        source_root = Path(settings.MEDIA_ROOT).resolve()
        destination_root = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
        records = []

        for model, field_name in FIELD_SPECS:
            for obj in model._default_manager.all().iterator():
                field = getattr(obj, field_name, None)
                name = str(getattr(field, "name", "") or "")
                if not name:
                    continue

                record = {
                    "model": f"{model._meta.app_label}.{model.__name__}",
                    "pk": obj.pk,
                    "field": field_name,
                    "name": name,
                    "status": "planned" if not execute else "pending",
                }

                try:
                    source_path = (source_root / name).resolve()
                except (OSError, RuntimeError, ValueError) as exc:
                    record.update(status="invalid_source", error=str(exc))
                    records.append(record)
                    continue

                try:
                    source_path.relative_to(source_root)
                except ValueError:
                    record.update(status="invalid_source", error="outside MEDIA_ROOT")
                    records.append(record)
                    continue

                if not source_path.is_file():
                    record.update(status="missing_source")
                    records.append(record)
                    continue

                try:
                    destination_path = (destination_root / name).resolve()
                    destination_path.relative_to(destination_root)
                except (OSError, RuntimeError, ValueError) as exc:
                    record.update(status="invalid_destination", error=str(exc))
                    records.append(record)
                    continue

                record.update(
                    source_size=source_path.stat().st_size,
                    source_sha256=_sha256(source_path),
                )

                if destination_path.exists():
                    destination_hash = _sha256(destination_path) if destination_path.is_file() else None
                    if destination_hash == record["source_sha256"]:
                        record.update(status="already_verified", destination_sha256=destination_hash)
                    else:
                        record.update(status="conflict", destination_sha256=destination_hash)
                    records.append(record)
                    continue

                if not execute:
                    records.append(record)
                    continue

                destination_path.parent.mkdir(parents=True, exist_ok=True)
                temp_name = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=destination_path.parent,
                        prefix=f".{destination_path.name}.",
                        delete=False,
                    ) as temp_handle:
                        temp_name = temp_handle.name
                        with source_path.open("rb") as source_handle:
                            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                                temp_handle.write(chunk)

                    temp_path = Path(temp_name)
                    if _sha256(temp_path) != record["source_sha256"]:
                        record.update(status="verification_failed")
                        temp_path.unlink(missing_ok=True)
                    else:
                        os.replace(temp_path, destination_path)
                        record.update(
                            status="copied_verified",
                            destination_sha256=record["source_sha256"],
                        )
                except OSError as exc:
                    if temp_name:
                        Path(temp_name).unlink(missing_ok=True)
                    record.update(status="copy_failed", error=str(exc))

                records.append(record)

        payload = {
            "execute": execute,
            "source_root": str(source_root),
            "destination_root": str(destination_root),
            "records": records,
        }
        self.stdout.write(json.dumps(payload, indent=2, sort_keys=True))

        manifest_path = options.get("manifest")
        if manifest_path:
            manifest = Path(manifest_path).resolve()
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self.stdout.write(f"Manifest written: {manifest}")
