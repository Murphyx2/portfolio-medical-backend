from datetime import date

from django.db.models import Q

from apps.core.filters import SearchFilterBase
from apps.core.services import patient_ids_matching_digits


def patient_age(patient_or_birth_date) -> int | None:
    """Age in years from a birth date; None when absent/unparseable.

    Accepts either a `Patient` instance (reads its `birth_date`) or a raw
    birth-date value (str/date) directly, so callers validating incoming
    request data (which isn't a saved instance yet) can reuse the same
    arithmetic as callers reading an existing row.
    """
    bd = getattr(patient_or_birth_date, "birth_date", patient_or_birth_date)
    if not bd:
        return None
    if isinstance(bd, str):
        try:
            bd = date.fromisoformat(bd)
        except ValueError:
            return None
    today = date.today()
    return (
        today.year
        - bd.year
        - ((today.month, today.day) < (bd.month, bd.day))
    )


class PatientSearchFilter(SearchFilterBase):
    """Search patients by name (plaintext search_name index) and, when the
    query contains digits, by the cedula/NSS last-4 index -- including the
    guardian's cedula for a minor patient, so front-desk staff can find a
    child by the only ID they may have on hand.

    Masked roles (IT/CENTER_MANAGER) are exempt entirely so a search cannot
    act as a PII existence oracle.
    """

    bypass_search_for_masked_role = True

    def always_lookups(self, term: str) -> Q:
        return Q(search_name__icontains=term)

    def digit_lookup(self, term: str) -> Q:
        return Q(id__in=patient_ids_matching_digits(term, include_guardian=True))
