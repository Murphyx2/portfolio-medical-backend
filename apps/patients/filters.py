from datetime import date

from django.db.models import Q
from rest_framework.filters import SearchFilter

from apps.core.services import is_masked_role
from apps.patients.models import Patient


def _patient_ids_matching_digits(term: str) -> list[int]:
    """Match a digit-containing term against decrypted cedula/NSS values.

    Non-digit characters (spaces, hyphens from the formatted display like
    ``001-1234567-8``) are stripped before matching, since cedula/NSS are stored
    as digits only.

    Cedula/NSS are Fernet-encrypted at rest, so the match happens in Python
    after decryption (a full-table scan). This is acceptable for an internal
    tool at current scale; a plaintext last-4-digit index would be the path if
    the dataset grows very large.
    """
    digits = "".join(ch for ch in term if ch.isdigit())
    if not digits:
        return []
    matched = []
    for patient in Patient.objects.all().only("id", "cedula", "nss"):
        if digits in (patient.cedula or "") or digits in (patient.nss or ""):
            matched.append(patient.id)
    return matched


def patient_age(patient) -> int | None:
    """Age in years from the (encrypted) birth date; None when absent."""
    bd = patient.birth_date
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
    query contains digits, by decrypted cedula/NSS.

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
                term_q |= Q(id__in=_patient_ids_matching_digits(term))
            q &= term_q
        return queryset.filter(q).distinct()
