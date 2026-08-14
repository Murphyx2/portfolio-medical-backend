from django.db.models import Q
from rest_framework.filters import SearchFilter

from apps.core.services import is_masked_role, patient_ids_matching_digits


class EncounterSearchFilter(SearchFilter):
    """Search encounters by patient name, doctor code, encounter number, or
    chief complaint and, when a term contains digits, by the patient's own
    cedula/NSS (never the guardian's -- guardian identifiers have no search
    index, same documented limitation as `apps.patients.filters
    .PatientSearchFilter`, which this mirrors).

    Multiple terms are AND-ed. Masked roles (IT/CENTER_MANAGER) are exempt
    from the digit-based patient lookup so a search cannot act as a PII
    existence oracle -- same guard as `PatientSearchFilter`.
    """

    def filter_queryset(self, request, queryset, view):
        terms = self.get_search_terms(request)
        if not terms:
            return queryset
        user = getattr(request, "user", None)
        masked = bool(
            user and getattr(user, "is_authenticated", False) and is_masked_role(user)
        )
        q = Q()
        for term in terms:
            # Patient-name substring matching is withheld from masked roles --
            # same PII-existence-oracle guard as PatientSearchFilter, since
            # patient_info.full_name is masked in the response but a hit
            # would still confirm a given name exists in the system.
            term_q = Q(doctor__code__icontains=term) | Q(encounter_number__icontains=term)
            if not masked:
                term_q |= Q(patient__search_name__icontains=term) | Q(
                    chief_complaint__icontains=term
                )
                if any(ch.isdigit() for ch in term):
                    term_q |= Q(patient_id__in=patient_ids_matching_digits(term))
            q &= term_q
        return queryset.filter(q).distinct()
