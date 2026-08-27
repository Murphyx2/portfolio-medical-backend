from django.db.models import Q

from apps.core.encryption import blind_index_digits


def patient_ids_matching_digits(term: str, *, include_guardian: bool = False):
    """Patient ids whose cedula/NSS match a search term's digits.

    Non-digit characters (spaces, hyphens from the formatted display like
    ``001-1234567-8``) are stripped before matching. The match runs in SQL so
    a digit search never has to decrypt every row in Python (M-01):

    - 5+ digits are matched exactly against the ``cedula_hash``/``nss_hash``
      blind index (a keyed hash of the *complete* number) -- this is precise,
      unlike the last-4 index, which can false-positive across patients who
      merely share the same trailing 4 digits. A 5+ digit term that isn't a
      complete cedula/NSS correctly matches nothing.
    - Fewer than 5 digits keeps the original last-4 index behavior: 4 digits
      match ``cedula_last4``/``nss_last4`` exactly, fewer use a substring
      match on those columns.

    ``include_guardian`` additionally matches any linked ``PatientGuardian``'s
    cedula (opt-in, default off) -- lets front-desk staff find a minor
    patient by their guardian's cedula, the only ID they may have on hand.
    Unlike the patient's own cedula/NSS this can legitimately match more than
    one patient (siblings can share a guardian), which is the intended
    behavior, not a false positive. Off by default so existing callers (e.g.
    the Encounters list's own search, which was deliberately scoped to the
    patient's own cedula only) are unaffected.

    Returns a ``values_list("id")`` queryset so the caller can use it as an
    ``id__in`` subquery; the underlying query runs once, in the database.
    ``include_guardian`` joins through the reverse ``guardians`` relation, so
    the result is deduplicated -- a patient with several guardians matching
    the same term must still yield one id, not one per guardian.
    """
    digits = "".join(ch for ch in term if ch.isdigit())
    from apps.patients.models import Patient

    if not digits:
        return Patient.objects.none().values_list("id", flat=True)
    if len(digits) >= 5:
        digest = blind_index_digits(digits)
        q = Q(cedula_hash=digest) | Q(nss_hash=digest)
        if include_guardian:
            q |= Q(guardians__cedula_hash=digest)
    else:
        tail = digits[-4:]
        if len(digits) >= 4:
            q = Q(cedula_last4=tail) | Q(nss_last4=tail)
            if include_guardian:
                q |= Q(guardians__cedula_last4=tail)
        else:
            q = Q(cedula_last4__icontains=tail) | Q(nss_last4__icontains=tail)
            if include_guardian:
                q |= Q(guardians__cedula_last4__icontains=tail)
    qs = Patient.objects.filter(q)
    if include_guardian:
        qs = qs.distinct()
    return qs.values_list("id", flat=True)
