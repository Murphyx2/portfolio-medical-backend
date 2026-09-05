"""Pure authorization/validation predicates that don't fit center-scoping
(scoping.py), roles (roles.py), or any other single domain bucket."""


def is_own_doctor_relation(user, doctor_profile) -> bool:
    """True unless ``user`` is a doctor managing a relation (schedule,
    appointment, encounter) tied to a different DoctorProfile than their
    own -- previously copy-pasted three times with the same body."""
    if not getattr(user, "is_doctor", False):
        return True
    own = getattr(user, "doctor_profile", None)
    return own is not None and doctor_profile is not None and doctor_profile.id == own.id
