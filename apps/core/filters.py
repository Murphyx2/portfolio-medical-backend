from django.db.models import Q
from rest_framework.filters import SearchFilter

from apps.core.services import is_masked_role


class SearchFilterBase(SearchFilter):
    """Shared mechanics for the patient/encounter/record search filters:
    multi-term AND-accumulation, digit-term detection, and the masked-role
    (IT/CENTER_MANAGER) PII-existence-oracle guard. Subclasses declare only
    which fields are searched -- the masked-role guard shape itself differs
    per resource and is controlled by ``bypass_search_for_masked_role``:

    - ``True`` (Patients): a masked role's search term is ignored entirely
      and the unfiltered queryset is returned -- the search UI still "works"
      but reveals nothing about which patients exist.
    - ``False`` (default -- Encounters, Records): the term still filters the
      list, but only against ``always_lookups``; ``gated_lookups`` (patient
      name, free-text narrative) and the digit-based patient lookup are
      withheld, since a hit there would still confirm a given patient/name
      exists even though the corresponding PII is masked in the response.

    Multiple terms are AND-ed (``q &= term_q`` per term); the digit lookup
    only applies to a term containing at least one digit.
    """

    bypass_search_for_masked_role = False

    def always_lookups(self, term: str) -> Q:
        """Q lookups applied for every user regardless of role."""
        raise NotImplementedError

    def gated_lookups(self, term: str) -> Q | None:
        """Additional Q lookups applied only for unmasked roles, or None."""
        return None

    def digit_lookup(self, term: str) -> Q | None:
        """Q lookup for a digit-bearing term, applied only for unmasked
        roles, or None to skip digit-based matching entirely."""
        return None

    def filter_queryset(self, request, queryset, view):
        terms = self.get_search_terms(request)
        if not terms:
            return queryset
        user = getattr(request, "user", None)
        masked = bool(
            user and getattr(user, "is_authenticated", False) and is_masked_role(user)
        )
        if masked and self.bypass_search_for_masked_role:
            return queryset
        q = Q()
        for term in terms:
            term_q = self.always_lookups(term)
            if not masked:
                gated_q = self.gated_lookups(term)
                if gated_q is not None:
                    term_q |= gated_q
                if any(ch.isdigit() for ch in term):
                    digit_q = self.digit_lookup(term)
                    if digit_q is not None:
                        term_q |= digit_q
            q &= term_q
        return queryset.filter(q).distinct()
