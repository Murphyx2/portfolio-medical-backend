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


def program_belongs_to_ars(ars, program) -> bool:
    """True unless both an ARS and a program are given and the program
    belongs to a different ARS."""
    return ars is None or program is None or program.ars_id == ars.id
