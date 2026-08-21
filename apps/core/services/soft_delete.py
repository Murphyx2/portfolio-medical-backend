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
