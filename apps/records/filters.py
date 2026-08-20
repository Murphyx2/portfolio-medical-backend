from django.db.models import Q

from apps.core.filters import SearchFilterBase
from apps.core.services import patient_ids_matching_digits


class RecordSearchFilter(SearchFilterBase):
    """Search records by title and by patient (name via the plaintext
    search_name index; cedula/NSS via the last-4 index when the query contains
    digits).

    Masked roles (IT/CENTER_MANAGER) are restricted to the record title so
    the search cannot act as a patient PII existence oracle (same rule as
    the Patients page).
    """

    def always_lookups(self, term: str) -> Q:
        return Q(title__icontains=term)

    def gated_lookups(self, term: str) -> Q:
        return Q(patient__search_name__icontains=term)

    def digit_lookup(self, term: str) -> Q:
        return Q(patient_id__in=patient_ids_matching_digits(term))
