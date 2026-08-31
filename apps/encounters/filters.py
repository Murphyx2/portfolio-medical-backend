from django.db.models import Q

from apps.core.filters import SearchFilterBase
from apps.core.services import patient_ids_matching_digits


class EncounterSearchFilter(SearchFilterBase):
    """Search encounters by patient name, doctor code, encounter number, or
    chief complaint and, when a term contains digits, by the patient's own
    cedula/NSS (never the guardian's -- guardian identifiers have no search
    index, same documented limitation as `apps.patients.filters
    .PatientSearchFilter`, which this mirrors).

    Masked roles (IT/CENTER_MANAGER) keep the doctor-code/encounter-number
    lookup but lose patient-name, chief-complaint, and digit-based matching
    -- same PII-existence-oracle guard as `PatientSearchFilter`, applied per
    field instead of bypassing the whole search.
    """

    def always_lookups(self, term: str) -> Q:
        return Q(services__doctor__code__icontains=term) | Q(encounter_number__icontains=term)

    def gated_lookups(self, term: str) -> Q:
        return Q(patient__search_name__icontains=term) | Q(chief_complaint__icontains=term)

    def digit_lookup(self, term: str) -> Q:
        return Q(patient_id__in=patient_ids_matching_digits(term))
