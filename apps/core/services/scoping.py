def user_accessible_center_ids(user) -> set[int]:
    """Center ids a doctor may work with (their approved center bindings).

    Kept doctor-specific and unchanged for existing callers. For the
    general "what can this user see" question -- including non-doctor
    staff -- use ``resolve_accessible_center_ids`` below, which is the one
    that knows how to resolve every role, not just DOCTOR.
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


def resolve_accessible_center_ids(user) -> set[int] | None:
    """The centers ``user`` may see, for every role -- ``None`` means
    unrestricted (full scope), a set means "only these centers".

    - unauthenticated / ADMIN: ``None`` (full scope; ADMIN is a platform-
      wide role by design).
    - DOCTOR: their approved ``DoctorCenterBinding`` center ids (via
      ``user_accessible_center_ids``) -- an empty set here correctly means
      "no approved bindings, no access", not "unrestricted".
    - RECEPTIONIST / IT / NURSE / CENTER_MANAGER: ``{user.center_id}`` if
      one is assigned, else ``None``. Nothing backfills ``User.center`` for
      these roles today, so "unassigned" must mean unrestricted -- treating
      it as "assigned to no center" would silently lock out every existing
      account the moment this ships.
    """
    if not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_admin", False):
        return None
    if getattr(user, "is_doctor", False):
        return user_accessible_center_ids(user)
    center_id = getattr(user, "center_id", None)
    return {center_id} if center_id else None


def scope_queryset(qs, user, *, center_field="center", owner_field=None, scope_doctors=True):
    """Scope ``qs`` to what ``user`` may access.

    - admin, or staff with no center assigned yet: full scope.
    - doctor, when ``scope_doctors`` is True (the default): rows in their
      approved centers, plus (optionally) rows they own via ``owner_field``
      (e.g. ``created_by``) -- a doctor with no approved bindings sees only
      their own rows, not nothing. This is the pre-existing behavior for
      Appointments/Encounters/Recetas -- unchanged.
    - doctor, when ``scope_doctors=False``: full scope, same as admin. Pass
      this for resources where doctor visibility is intentionally
      unrestricted -- Patients and the Records app both are, on purpose
      (see test_security_fixes.py::test_doctor_sees_patients_across_all_centers
      and test_record_image_list_is_unscoped_for_doctor) -- so this function
      can still be reused there for the *non-doctor* staff scoping this was
      extended to support, without re-scoping doctors by accident.
    - other staff with a center assigned (``User.center``): rows in that one
      center, PLUS rows with a null ``center_field`` -- CLAUDE.md's
      documented invariant is that a nullable center means "unbound,
      visible to all staff," not "visible to no one." This only applies to
      the non-doctor branch: the doctor/``owner_field`` behavior below is
      pre-existing (Appointments/Encounters/Recetas) and intentionally does
      *not* auto-include null-center rows -- changing that would silently
      widen what a center-bound doctor sees on resources that were already
      tested and correct.

    ``center_field`` is the relation path to the center FK (default
    ``"center"``; use e.g. ``"record__center"`` when scoping through a join).
    """
    is_doctor = getattr(user, "is_doctor", False)
    if is_doctor and not scope_doctors:
        return qs
    ids = resolve_accessible_center_ids(user)
    if ids is None:
        return qs
    from django.db.models import Q

    if is_doctor:
        q = Q(**{f"{center_field}_id__in": ids})
        if owner_field:
            q |= Q(**{owner_field: user})
    else:
        q = Q(**{f"{center_field}_id__in": ids}) | Q(**{f"{center_field}__isnull": True})
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
