# audit/middleware.py
from __future__ import annotations

import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse


class AuditContextMiddleware:
    """
    Adds a per-request correlation id:
      - request.audit_request_id
      - Response header: X-Request-ID

    Useful to correlate AuditLog rows + server logs for the same request.
    """

    HEADER_NAME = "X-Request-ID"
    META_KEY = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    @staticmethod
    def _clean_id(val: str | None) -> str:
        """
        Normalize incoming request-id:
        - trim
        - keep it reasonably small
        - fallback to generated if empty
        """
        v = (val or "").strip()
        # prevent header abuse / log pollution
        if len(v) > 128:
            v = v[:128]
        return v

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Prefer upstream request id if present, else generate
        incoming = ""
        try:
            # Django 2.2+ request.headers
            incoming = self._clean_id(request.headers.get(self.HEADER_NAME))
        except Exception:
            incoming = ""

        if not incoming:
            # Fallback to META (works everywhere)
            incoming = self._clean_id(request.META.get(self.META_KEY))

        request.audit_request_id = incoming or uuid.uuid4().hex

        response = self.get_response(request)

        # Expose id back to client (safe, no PHI)
        try:
            response[self.HEADER_NAME] = request.audit_request_id
        except Exception:
            pass

        return response