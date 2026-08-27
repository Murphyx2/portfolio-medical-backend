from django.db.models import Q

from apps.core.filters import SearchFilterBase
from apps.core.services import patient_ids_matching_digits


class RecordSearchFilter(SearchFilterBase):
    """Search expedientes by patient name (plaintext search_name index) and,
    when the query contains digits, by cedula/NSS (last-4 index) -- spec §5:
    "Search bar. Must keep matching at least nombre, Cédula, NSS."

    Records has no free-text field of its own to search anymore (the old
    per-record `title` moved to RecordEntry-level Dx/Tx/Observaciones, which
    aren't searched here), so name matching is unconditional (`always_lookups`)
    rather than gated -- moot in practice since IT/CENTER_MANAGER can't even
    reach this endpoint (IsAdminDoctorOrNurse), but keeps this filter correct
    on its own terms rather than relying solely on the permission layer.
    """

    def always_lookups(self, term: str) -> Q:
        return Q(patient__search_name__icontains=term)

    def digit_lookup(self, term: str) -> Q:
        return Q(patient_id__in=patient_ids_matching_digits(term))
