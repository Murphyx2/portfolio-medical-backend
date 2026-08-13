from datetime import date

from django.db.models import Q
from rest_framework.filters import SearchFilter

from apps.core.services import is_masked_role, patient_ids_matching_digits
from apps.patients.models import Patient


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


class PatientSearchFilter(SearchFilter):
    """Search patients by name (plaintext search_name index) and, when the
    query contains digits, by the cedula/NSS last-4 index.

    Multiple terms are AND-ed. Masked roles (IT/CENTER_MANAGER) are exempt so a
    search cannot act as a PII existence oracle.
    """

    def filter_queryset(self, request, queryset, view):
        terms = self.get_search_terms(request)
        if not terms:
            return queryset
        user = getattr(request, "user", None)
        if (
            user
            and getattr(user, "is_authenticated", False)
            and is_masked_role(user)
        ):
            return queryset
        q = Q()
        for term in terms:
            term_q = Q(search_name__icontains=term)
            if any(ch.isdigit() for ch in term):
                term_q |= Q(id__in=patient_ids_matching_digits(term))
            q &= term_q
        return queryset.filter(q).distinct()
