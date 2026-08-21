def user_accessible_center_ids(user) -> set[int]:
    """Center ids a user may work with.

    Admins can access all centers. Doctors are scoped to their approved
    center bindings. Other staff roles have no center relationship in the
    data model yet, so they are treated as center-agnostic (full scope).

    NOTE: an empty return value is ambiguous (admin=all, staff=center-
    agnostic, doctor-no-bindings=nothing). Prefer ``scope_queryset`` below
    for new callers; it resolves that ambiguity into a shaped queryset.
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


def scope_queryset(qs, user, *, center_field="center", owner_field=None):
    """Scope ``qs`` to what ``user`` may access, resolving the ambiguous empty
    set of ``user_accessible_center_ids`` into the correct shape:

    - admins and non-doctor staff: full scope (their empty center set means
      "all", never "nothing")
    - doctors: rows in their approved centers, plus (optionally) rows they own
      via ``owner_field`` (e.g. ``created_by``) -- a doctor with no approved
      bindings sees only their own rows, not nothing.

    ``center_field`` is the relation path to the center FK (default
    ``"center"``; use e.g. ``"record__center"`` when scoping through a join).
    """
    if not getattr(user, "is_doctor", False):
        return qs
    from django.db.models import Q

    q = Q(**{f"{center_field}_id__in": user_accessible_center_ids(user)})
    if owner_field:
        q |= Q(**{owner_field: user})
    return qs.filter(q)


def can_write_center(user, center) -> bool:
    """Single home for the "doctor approved for this center" write-side
    rule -- previously re-encoded with three different query shapes across
    records/doctors/patients serializers. True for anyone who isn't a
    doctor, and for a doctor when ``center`` is None (unbound/centerless
    rows are writable by any doctor)."""
    if not getattr(user, "is_doctor", False) or center is None:
        return True
    return center.id in user_accessible_center_ids(user)
