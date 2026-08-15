from django.core.signing import BadSignature, TimestampSigner
from django.db.models import Q

from apps.core.encryption import blind_index_digits
from apps.core.models import AuditLog

# How long a signed media URL stays valid (seconds).
MEDIA_TOKEN_MAX_AGE = 60 * 60


def patient_ids_matching_digits(term: str, *, include_guardian: bool = False):
    """Patient ids whose cedula/NSS match a search term's digits.

    Non-digit characters (spaces, hyphens from the formatted display like
    ``001-1234567-8``) are stripped before matching. The match runs in SQL so
    a digit search never has to decrypt every row in Python (M-01):

    - 5+ digits are matched exactly against the ``cedula_hash``/``nss_hash``
      blind index (a keyed hash of the *complete* number) -- this is precise,
      unlike the last-4 index, which can false-positive across patients who
      merely share the same trailing 4 digits. A 5+ digit term that isn't a
      complete cedula/NSS correctly matches nothing.
    - Fewer than 5 digits keeps the original last-4 index behavior: 4 digits
      match ``cedula_last4``/``nss_last4`` exactly, fewer use a substring
      match on those columns.

    ``include_guardian`` additionally matches ``guardian_cedula_hash``/
    ``guardian_cedula_last4`` (opt-in, default off) -- lets front-desk staff
    find a minor patient by their guardian's cedula, the only ID they may
    have on hand. Unlike the patient's own cedula/NSS this can legitimately
    match more than one patient (siblings can share a guardian), which is
    the intended behavior, not a false positive. Off by default so existing
    callers (e.g. the Encounters list's own search, which was deliberately
    scoped to the patient's own cedula only) are unaffected.

    Returns a ``values_list("id")`` queryset so the caller can use it as an
    ``id__in`` subquery; the underlying query runs once, in the database.
    """
    digits = "".join(ch for ch in term if ch.isdigit())
    from apps.patients.models import Patient

    if not digits:
        return Patient.objects.none().values_list("id", flat=True)
    if len(digits) >= 5:
        digest = blind_index_digits(digits)
        q = Q(cedula_hash=digest) | Q(nss_hash=digest)
        if include_guardian:
            q |= Q(guardian_cedula_hash=digest)
    else:
        tail = digits[-4:]
        if len(digits) >= 4:
            q = Q(cedula_last4=tail) | Q(nss_last4=tail)
            if include_guardian:
                q |= Q(guardian_cedula_last4=tail)
        else:
            q = Q(cedula_last4__icontains=tail) | Q(nss_last4__icontains=tail)
            if include_guardian:
                q |= Q(guardian_cedula_last4__icontains=tail)
    return Patient.objects.filter(q).values_list("id", flat=True)


def sign_media_token(file_path: str) -> str:
    """Short-lived signed token for an authenticated media URL."""
    return TimestampSigner().sign(file_path)


def verify_media_token(file_path: str, token: str, max_age: int = MEDIA_TOKEN_MAX_AGE) -> bool:
    try:
        return TimestampSigner().unsign(token, max_age=max_age) == file_path
    except BadSignature:
        return False


def user_accessible_center_ids(user) -> set[int]:
    """Center ids a user may work with.

    Admins can access all centers. Doctors are scoped to their approved
    center bindings. Other staff roles have no center relationship in the
    data model yet, so they are treated as center-agnostic (full scope).
    """
    if not getattr(user, "is_authenticated", False):
        return set()
    if getattr(user, "is_admin", False):
        return set()
    if getattr(user, "is_doctor", False):
        from apps.centers.models import DoctorCenterBinding

        return set(
            DoctorCenterBinding.objects.filter(
                doctor__user=user, approved=True
            ).values_list("center_id", flat=True)
        )
    return set()


def log_audit(
    *,
    user,
    action: str,
    target=None,
    target_type: str = "",
    target_id: int | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    if target is not None:
        target_type = target_type or target.__class__.__name__
        target_id = target.pk
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address=ip_address,
        details=details or {},
    )


def is_masked_role(user) -> bool:
    """IT and CENTER_MANAGER see masked PII; all other staff see full PII."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    return not (
        getattr(user, "is_admin", False)
        or getattr(user, "is_doctor", False)
        or getattr(user, "is_nurse", False)
        or getattr(user, "is_receptionist", False)
    )


def client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def can_view_inactive(user) -> bool:
    """The single place a future per-role visibility rule would change.

    Every check for "may this user see/restore deactivated rows" (ViewSet
    querysets, the caching bypass, the restore permission, every serializer's
    writable-active gate) funnels through this one function -- none of those
    call sites re-check the role directly.
    """
    return bool(
        user and getattr(user, "is_authenticated", False) and getattr(user, "is_admin", False)
    )


def soft_delete_field_name(model) -> str | None:
    """Name of the soft-delete flag on a model, or None if it isn't one.

    `active` for models using the SoftDeleteModel mixin, `is_active` for
    User (which reuses Django's built-in login-gate field instead of a
    duplicate flag), None for anything not soft-deletable.
    """
    if hasattr(model, "all_objects"):
        return "active"
    if hasattr(model, "is_active"):
        return "is_active"
    return None


def deactivate_with_cascade(instance, seen: set | None = None) -> None:
    """Soft-delete instance and cascade into related rows exactly the way
    on_delete=CASCADE would have hard-deleted them: walk
    instance._meta.related_objects, follow only CASCADE edges (PROTECT/
    SET_NULL relations are left untouched, matching current DB semantics),
    and recurse. Idempotent -- an already-inactive instance (or one already
    visited in this call, in case of a diamond in the relation graph) is
    skipped. Shared by the DRF perform_destroy path (apps.core.mixins) and
    the Django-admin delete path (apps.core.admin) so both stay consistent.
    """
    from django.db import models as dj_models

    field = soft_delete_field_name(type(instance))
    if field is None:
        return
    seen = seen if seen is not None else set()
    key = (type(instance), instance.pk)
    if key in seen or not getattr(instance, field):
        return
    seen.add(key)
    setattr(instance, field, False)
    instance.save(update_fields=[field])
    for related in instance._meta.related_objects:
        if related.on_delete is not dj_models.CASCADE:
            continue
        if soft_delete_field_name(related.related_model) is None:
            continue
        accessor = related.get_accessor_name()
        if accessor is None:
            continue
        if related.one_to_one:
            child = getattr(instance, accessor, None)
            children = [child] if child is not None else []
        else:
            children = list(getattr(instance, accessor).all())
        for child in children:
            deactivate_with_cascade(child, seen)
