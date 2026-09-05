"""apps.core.services was a single 255-line flat file holding 6+ unrelated
domains (patient search, media tokens, center scoping, audit, masking-role
predicate, soft-delete, plus a couple of stray authorization predicates).
Split into per-domain modules below; every existing
``from apps.core.services import X`` import site keeps working unchanged
via this re-export shim, so no caller needed to change."""

from apps.core.services.audit import client_ip, log_audit
from apps.core.services.media import MEDIA_TOKEN_MAX_AGE, sign_media_token, verify_media_token
from apps.core.services.predicates import is_own_doctor_relation
from apps.core.services.roles import is_masked_role
from apps.core.services.scoping import (
    can_write_center,
    resolve_accessible_center_ids,
    scope_queryset,
    user_accessible_center_ids,
)
from apps.core.services.search import patient_ids_matching_digits
from apps.core.services.soft_delete import (
    can_view_inactive,
    deactivate_with_cascade,
    soft_delete_field_name,
)

__all__ = [
    "client_ip",
    "log_audit",
    "MEDIA_TOKEN_MAX_AGE",
    "sign_media_token",
    "verify_media_token",
    "is_own_doctor_relation",
    "is_masked_role",
    "can_write_center",
    "resolve_accessible_center_ids",
    "scope_queryset",
    "user_accessible_center_ids",
    "patient_ids_matching_digits",
    "can_view_inactive",
    "deactivate_with_cascade",
    "soft_delete_field_name",
]
