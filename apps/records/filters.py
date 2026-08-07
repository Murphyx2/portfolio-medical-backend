from django.db.models import Q
from rest_framework.filters import SearchFilter

from apps.core.services import is_masked_role, patient_ids_matching_digits


class RecordSearchFilter(SearchFilter):
    """Search records by title and by patient (name via the plaintext
    search_name index; cedula/NSS via the last-4 index when the query contains
    digits).

    Multiple terms are AND-ed. Masked roles (IT/CENTER_MANAGER) are restricted
    to the record title so the search cannot act as a patient PII existence
    oracle (same rule as the Patients page).
    """

    def filter_queryset(self, request, queryset, view):
        terms = self.get_search_terms(request)
        if not terms:
            return queryset
        user = getattr(request, "user", None)
        masked = bool(
            user
            and getattr(user, "is_authenticated", False)
            and is_masked_role(user)
        )
        q = Q()
        for term in terms:
            term_q = Q(title__icontains=term)
            if not masked:
                term_q |= Q(patient__search_name__icontains=term)
                if any(ch.isdigit() for ch in term):
                    term_q |= Q(patient_id__in=patient_ids_matching_digits(term))
            q &= term_q
        return queryset.filter(q).distinct()
