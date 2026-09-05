"""Service-layer helpers for apps.services -- mirrors apps/core/services.py's
convention of keeping cross-cutting resolution logic out of models/serializers."""

from decimal import Decimal

from apps.services.models import Service, ServicePrice


def resolve_line_price(service: Service, ars_covered: bool, ars, ars_program) -> Decimal:
    """The Co-pago to charge for one EncounterService line, given the
    encounter's ARS/Program context.

    Uncovered ("Particular") lines, or lines with no ARS at all, always
    price off Service.privado -- there's no ARS to look an override up
    against. Covered lines resolve most-specific-first: an ARS+Program
    override, then an ARS-level override, falling back to Service.co_pago
    (the implicit global default) if neither ServicePrice row exists.
    """
    if not ars_covered or ars is None:
        return service.privado

    if ars_program is not None:
        hit = ServicePrice.objects.filter(
            service=service, ars=ars, ars_program=ars_program
        ).first()
        if hit is not None:
            return hit.co_pago

    hit = ServicePrice.objects.filter(service=service, ars=ars, ars_program__isnull=True).first()
    if hit is not None:
        return hit.co_pago

    return service.co_pago
