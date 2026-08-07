from django.db.models import Q
from rest_framework.filters import SearchFilter

from apps.core.services import is_masked_role
from apps.patients.models import Patient


def _patient_ids_matching_digits(term: str) -> list[int]:
    """Records whose patient's decrypted cedula/NSS contains the term.

    Non-digit characters (spaces, hyphens from the formatted display like
    ``001-1234567-8``) are stripped before matching, since cedula/NSS are stored
    as digits only.
    """
    digits = "".join(ch for ch in term if ch.isdigit())
    if not digits:
        return []
    matched = []
    for patient in Patient.objects.all().only("id", "cedula", "nss"):
        if digits in (patient.cedula or "") or digits in (patient.nss or ""):
            matched.append(patient.id)
    return matched


class RecordSearchFilter(SearchFilter):
    """Search records by title and by patient (name via the plaintext
    search_name index; decrypted cedula/NSS when the query contains digits).

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
                    term_q |= Q(patient_id__in=_patient_ids_matching_digits(term))
            q &= term_q
        return queryset.filter(q).distinct()
