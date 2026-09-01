"""Engine for the one seeded report type, "Servicios prestados"
(Requirements/ReportPage/REPORTES_REQUIREMENTS.md section 4/6).

Implemented as a plain Django ORM queryset (the requirement allows "one
queryset or view") rather than a hand-written Postgres view -- there is no
existing precedent in this codebase for RunSQL-created views, and a
queryset is simpler to test and maintain.
"""

from dataclasses import dataclass
from datetime import datetime

from django.db import connection, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.encounters.models import Encounter, EncounterService

MAX_ROWS = 20_000

ES_MONTH_NAMES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


class ReportTooLargeError(Exception):
    """Raised when the underlying (pre-grouping) row count exceeds MAX_ROWS."""


@dataclass(frozen=True)
class ServiceLine:
    name: str
    cant: int
    precio: object  # Decimal
    valor: object  # Decimal


def month_label(year: int, month: int) -> str:
    return f"{ES_MONTH_NAMES[month - 1]} {year}"


def ars_program_label(ars, programa) -> str:
    """ARS + Programa display label. No ARS at all -> "Particular - (sin
    programa)"; ARS present but no programa -> "{ARS} - (sin programa)"."""
    if ars is None:
        return "Particular - (sin programa)"
    if programa is None:
        return f"{ars.name} - (sin programa)"
    return f"{ars.name} - {programa.name}"


def _month_range(year: int, month: int):
    """Half-open [start, end) bound for the given month, as a sargable range
    filter -- __year=/__month= forces a per-row EXTRACT() that can't use any
    index on the underlying Coalesce()d columns."""
    start = timezone.make_aware(datetime(year, month, 1))
    if month == 12:
        end = timezone.make_aware(datetime(year + 1, 1, 1))
    else:
        end = timezone.make_aware(datetime(year, month + 1, 1))
    return start, end


def _base_queryset(*, year: int, month: int, centro_id: int | None):
    start, end = _month_range(year, month)
    qs = EncounterService.objects.filter(encounter__status=Encounter.Status.COMPLETED)
    qs = qs.annotate(
        _month_basis=Coalesce("encounter__completed_at", "encounter__created_at")
    ).filter(_month_basis__gte=start, _month_basis__lt=end)
    if centro_id:
        qs = qs.filter(encounter__center_id=centro_id)
    return qs


def _apply_slice(qs, *, ars_id: int | None, programa_id: int | None):
    """Slice by the coverage actually billed for each line: a service marked
    ``ars_covered=False`` always falls into the Particular slice (ars_id is
    None), regardless of the encounter's ARS -- see EncounterService.ars_covered."""
    if ars_id is None:
        return qs.filter(Q(ars_covered=False) | Q(encounter__ars_id__isnull=True))
    qs = qs.filter(ars_covered=True, encounter__ars_id=ars_id)
    if programa_id is None:
        return qs.filter(encounter__ars_program_id__isnull=True)
    return qs.filter(encounter__ars_program_id=programa_id)


def _set_read_only_timeout():
    # Postgres-only guard: SQLite (used in tests) has no statement_timeout /
    # transaction read-only session setting.
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = 15000")
        cursor.execute("SET TRANSACTION READ ONLY")


def servicios_prestados_rows(
    *, year: int, month: int, ars_id: int | None, programa_id: int | None, centro_id: int | None
) -> list[ServiceLine]:
    """Rows for one ARS x Programa slice, grouped by service, sorted by
    name, ready to hand to the Excel builder."""
    with transaction.atomic():
        _set_read_only_timeout()
        qs = _apply_slice(_base_queryset(year=year, month=month, centro_id=centro_id), ars_id=ars_id, programa_id=programa_id)
        if qs.count() > MAX_ROWS:
            raise ReportTooLargeError(
                "El reporte supera el limite de 20,000 filas. Reduzca el rango."
            )
        grouped = (
            qs.values("service__name", "service__co_pago")
            .annotate(cant=Sum("quantity"))
            .order_by("service__name")
        )
        return [
            ServiceLine(
                name=row["service__name"],
                cant=row["cant"],
                precio=row["service__co_pago"],
                valor=row["cant"] * row["service__co_pago"],
            )
            for row in grouped
        ]


def distinct_ars_program_slices(
    *, year: int, month: int, centro_id: int | None
) -> list[tuple]:
    """Distinct (ars, ars_program) pairs -- as model instances, not just
    ids, so the caller can build the display label without a second
    lookup -- among COMPLETED encounters with a service line that month.

    The effective slice is derived per-line, not per-encounter: a line with
    ars_covered=False always normalizes to the Particular slice (None, None)
    regardless of the encounter's own ARS -- see _apply_slice."""
    qs = _base_queryset(year=year, month=month, centro_id=centro_id)
    triples = (
        # .order_by() clears EncounterService's default `ordering = ["id"]"
        # -- left in place, Django keeps `id` in the query's ORDER BY/SELECT
        # alongside the values_list() columns, which makes every row
        # "distinct" (id always differs) instead of collapsing by
        # (ars_id, ars_program_id) as intended.
        qs.order_by()
        .values_list("encounter__ars_id", "encounter__ars_program_id", "ars_covered")
        .distinct()
    )
    from apps.ars.models import ARS, ARSProgram

    ars_cache = {a.id: a for a in ARS.all_objects.all()}
    program_cache = {p.id: p for p in ARSProgram.all_objects.all()}
    pairs = {
        (ars_id, programa_id) if ars_covered else (None, None)
        for ars_id, programa_id, ars_covered in triples
    }
    return [
        (ars_cache.get(ars_id), program_cache.get(programa_id))
        for ars_id, programa_id in pairs
    ]
