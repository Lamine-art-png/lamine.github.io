from __future__ import annotations

import re
import uuid


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")


def bounded_request_id(value: str | None) -> str:
    candidate = str(value or "").strip()
    if REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return f"req_{uuid.uuid4().hex}"
