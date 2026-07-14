"""Server-side validation of dynamic-form submissions (proposal §5, §8).

The widget renders a service's form schema and posts back a submission. We never
trust that submission: every field is re-validated here against the catalog
schema before it can reach the pricing engine. Returns cleaned, typed params or
raises FormError with per-field messages.
"""
from __future__ import annotations

from typing import Any

from . import catalog


class FormError(Exception):
    """Raised when a submission fails validation. `errors` is {field: message}."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def _coerce(field: dict, raw: Any) -> Any:
    ftype = field["type"]
    if ftype == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, int):  # 0/1 from some form encoders
            return bool(raw)
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        raise ValueError("must be true or false")
    if ftype == "integer":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError("must be a whole number")
        if "min" in field and value < field["min"]:
            raise ValueError(f"must be at least {field['min']}")
        if "max" in field and value > field["max"]:
            raise ValueError(f"must be at most {field['max']}")
        return value
    if ftype == "enum":
        value = str(raw)
        if value not in field["options"]:
            raise ValueError(f"must be one of {', '.join(field['options'])}")
        return value
    # string / fallback
    return str(raw).strip()


def validate_submission(service_key: str, raw: dict) -> dict:
    """Validate raw form data for a service; return cleaned params."""
    try:
        service = catalog.get(service_key)
    except KeyError:
        raise FormError({"service": "unknown service"})

    raw = raw or {}
    cleaned: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for field in service.form_fields:
        name = field["name"]
        present = name in raw and raw[name] not in (None, "")
        if not present:
            if field.get("required") and "default" not in field:
                errors[name] = "this field is required"
            else:
                cleaned[name] = field.get("default")
            continue
        try:
            cleaned[name] = _coerce(field, raw[name])
        except ValueError as exc:
            errors[name] = str(exc)

    if errors:
        raise FormError(errors)
    return cleaned
