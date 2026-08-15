"""Output masking for PII and clinical narrative.

One deep module owning *how* serialized response data is redacted, so the
per-serializer ``to_representation`` blocks all funnel through here instead of
re-implementing the role checks and field sets independently (which is how the
policy previously drifted).

Two independent axes (a single user can sit on both):
- masked-role redaction (invariant #1): IT and CENTER_MANAGER see redacted
  patient PII (names, identifiers, contact, clinical summary) -- controlled by
  ``is_masked_role``.
- clinical redaction: anyone who isn't a doctor/nurse/admin sees free-text
  clinical narrative (diagnosis, notes, chief complaint) masked -- doctors,
  nurses and admins are the clinical roles.
"""

from apps.core.services import is_masked_role


def mask(value) -> str:
    """Redact a string, keeping a hint of its shape: ``ab••••yz`` for longer
    values, ``••••`` for anything 4 chars or shorter. Falsy input passes
    through unchanged so callers don't need their own truthiness guards."""
    if not value:
        return value
    if len(value) <= 4:
        return "••••"
    return f"{value[:2]}••••{value[-2:]}"


def is_clinical_role(user) -> bool:
    return bool(
        getattr(user, "is_doctor", False)
        or getattr(user, "is_nurse", False)
        or getattr(user, "is_admin", False)
    )


def _apply_mask_plan(data, user, fields, nulls):
    for field in fields:
        if data.get(field):
            data[field] = mask(str(data[field]))
    for field in nulls:
        data[field] = None


def _apply_mask_plan_nested(data, user, nested, nested_nulls):
    for field, subs in nested:
        obj = data.get(field)
        if not obj:
            continue
        for sub in subs:
            if obj.get(sub):
                obj[sub] = mask(str(obj[sub]))
    for field, subs in nested_nulls:
        obj = data.get(field)
        if not obj:
            continue
        for sub in subs:
            obj[sub] = None


def apply_masking(
    data,
    user,
    *,
    masked_fields=(),
    masked_nulls=(),
    masked_nested=(),
    masked_nested_nulls=(),
    clinical_fields=(),
    clinical_nested=(),
):
    """Redact serialized ``data`` (mutated and returned) for the requesting
    user, using declarative specs:

    - ``masked_fields`` / ``masked_nulls``: top-level fields redacted or set
      to None for masked roles.
    - ``masked_nested`` / ``masked_nested_nulls``: ``(field, (sub, ...))``
      tuples -- subfields inside a nested dict (e.g. ``patient_info``).
    - ``clinical_fields`` / ``clinical_nested``: free-text narrative fields
      redacted for non-clinical roles (``clinical_nested`` targets a list of
      dicts, e.g. encounter diagnoses).
    """
    user = user if getattr(user, "is_authenticated", False) else None
    if user and is_masked_role(user):
        _apply_mask_plan(data, user, masked_fields, masked_nulls)
        _apply_mask_plan_nested(data, user, masked_nested, masked_nested_nulls)
    if user and not is_clinical_role(user):
        for field in clinical_fields:
            if data.get(field):
                data[field] = mask(str(data[field]))
        for field, subs in clinical_nested:
            for item in data.get(field) or []:
                for sub in subs:
                    if item.get(sub):
                        item[sub] = mask(str(item[sub]))
    return data


def mask_doctor_contact(data, user, instance):
    """M-03: doctor contact PII is only for admins/IT and the doctor themself;
    other staff keep name/specialty but see masked contact. Exception:
    receptionists need unmasked phone/email to coordinate appointments, but
    license_number/bio stay hidden from them too."""
    is_self = bool(user and getattr(instance, "user_id", None) == getattr(user, "id", None))
    if not user or user.is_admin or user.is_it or is_self:
        return data
    if data.get("license_number"):
        data["license_number"] = mask(str(data["license_number"]))
    if not getattr(user, "is_receptionist", False):
        if data.get("contact_phone"):
            data["contact_phone"] = mask(str(data["contact_phone"]))
        if data.get("contact_email"):
            data["contact_email"] = mask(str(data["contact_email"]))
    data["bio"] = None
    return data
