"""Upsert Service.privado (and create missing services) from the official
INCAF tarifario Excel workbook (one sheet per category: SERVICIOS,
PROCEDIMIENTOS, IMAGENES, VACUNAS, CARDIOLOGIA -- each row is
No / SIMON code / description / ... / price).

Usage:
    python manage.py import_tarifario --file "/path/to/TARIFARIO.xlsx" [--dry-run]
    python manage.py import_tarifario --file "/path/to/TARIFARIO.xlsx" --deactivate-legacy-consulta

Safe to re-run whenever the tarifario changes: matching is by normalized
service name (case-insensitive, whitespace-collapsed) across every
ServiceType, not just the sheet's default category -- a name that already
exists in the catalog only has its `privado` refreshed (SIMON code, type,
and co_pago are left untouched, since those may have been curated
separately from this price sheet). A name with no existing match is
created fresh, with co_pago defaulted to the same value as privado (no
insurance-specific default exists in this workbook -- adjust via the
Services page or a ServicePrice override once a real co-pago is known).

--deactivate-legacy-consulta soft-deletes every Service under the
placeholder "CONSULTA" ServiceType (seed/demo rows with non-SIMON codes
like 100001-100010) once the real catalog has been loaded -- run it in the
same invocation that first loads the real data, or as a separate one-off
afterward.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import openpyxl
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.services.models import Service, ServiceType

# Sheet name -> ServiceType name, used only when CREATING a brand-new
# service. A name that already matches an existing Service keeps that
# service's current type untouched regardless of which sheet lists it --
# e.g. "NEBULIZACION (EMERGENCIA/URGENCIAS)" already lives under Emergencia
# even though the tarifario lists it on the PROCEDIMIENTOS sheet.
SHEET_DEFAULT_TYPE = {
    "SERVICIOS": "Admision",
    "PROCEDIMIENTOS": "Procedimiento",
    "IMAGENES": "Imagenes",
    "VACUNAS": "Vacunacion",
    "CARDIOLOGIA": "Cardiologia",
}

PLACEHOLDER_SIMON = "0000"


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().upper()


def _simon_code(raw) -> str:
    if raw is None:
        return PLACEHOLDER_SIMON
    text = str(raw).strip()
    if not text or not text.isdigit():
        return PLACEHOLDER_SIMON
    return text[:6]


class Command(BaseCommand):
    help = "Upsert Service.privado (and create missing services) from the tarifario Excel."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the tarifario .xlsx file")
        parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
        parser.add_argument(
            "--deactivate-legacy-consulta",
            action="store_true",
            help='Soft-delete (active=False) every Service under the placeholder "CONSULTA" ServiceType',
        )

    def _build_name_index(self, exclude_ids):
        """Normalized-name -> Service, preferring active rows over inactive
        ones and, when two *active* rows share a name (a real, observed
        case: "ELECTROCARDIOGRAMA" exists both for real under Procedimiento
        and as a legacy placeholder under the demo "CONSULTA" type), the one
        NOT under the placeholder "CONSULTA" type -- logging every such
        collision either way so it's visible in the run output rather than
        silently resolved by dict/queryset iteration order."""
        by_name: dict[str, Service] = {}
        collisions = []
        for svc in Service.objects.exclude(pk__in=exclude_ids).order_by("id"):
            key = _normalize(svc.name)
            prior = by_name.get(key)
            if prior is not None:
                collisions.append((svc.name, prior.type.name, svc.type.name))
                if prior.type.name == "CONSULTA" and svc.type.name != "CONSULTA":
                    by_name[key] = svc
                continue
            by_name[key] = svc
        for svc in Service.all_objects.filter(active=False).exclude(pk__in=exclude_ids).order_by("id"):
            by_name.setdefault(_normalize(svc.name), svc)
        return by_name, collisions

    def handle(self, *args, **options):
        path = options["file"]
        dry_run = options["dry_run"]
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except FileNotFoundError:
            raise CommandError(f"File not found: {path}")

        type_cache: dict[str, ServiceType] = {}

        def get_type(name: str) -> ServiceType:
            # Case-insensitive lookup before create: ServiceType.save()
            # uppercases on every save, but some pre-existing rows were
            # seeded directly (bypassing save()) and kept mixed case --
            # get_or_create(name=name.upper()) would silently create a
            # second, all-caps duplicate of an already-existing type
            # instead of reusing it (a real bug hit and fixed once already;
            # don't reintroduce it).
            if name not in type_cache:
                svc_type = ServiceType.objects.filter(name__iexact=name).first()
                if svc_type is None:
                    svc_type = ServiceType.objects.create(name=name.upper())
                type_cache[name] = svc_type
            return type_cache[name]

        created, updated, unchanged, skipped = [], [], [], []
        deactivated = []

        with transaction.atomic():
            deactivated_ids: set[int] = set()
            if options["deactivate_legacy_consulta"]:
                for svc in Service.objects.filter(type__name="CONSULTA"):
                    deactivated.append(svc.name)
                    deactivated_ids.add(svc.pk)
                    if not dry_run:
                        svc.active = False
                        svc.save(update_fields=["active"])

            existing_by_name, collisions = self._build_name_index(deactivated_ids)

            for sheet_name in wb.sheetnames:
                default_type_name = SHEET_DEFAULT_TYPE.get(sheet_name.strip().upper())
                if default_type_name is None:
                    self.stdout.write(self.style.WARNING(f"Skipping unrecognized sheet: {sheet_name!r}"))
                    continue
                ws = wb[sheet_name]
                for row in ws.iter_rows(values_only=True):
                    if not row or row[0] is None:
                        continue
                    try:
                        int(row[0])
                    except (TypeError, ValueError):
                        continue  # header/title row, not a data row
                    simon_raw, desc = row[1], row[2]
                    if not desc or not str(desc).strip():
                        continue
                    price_raw = next((v for v in reversed(row) if v is not None), None)
                    try:
                        price = Decimal(str(price_raw)).quantize(Decimal("0.01"))
                    except (InvalidOperation, TypeError):
                        skipped.append((sheet_name, str(desc).strip(), price_raw))
                        continue

                    name = str(desc).strip()
                    key = _normalize(name)
                    existing = existing_by_name.get(key)
                    if existing is not None:
                        if existing.privado != price:
                            old = existing.privado
                            existing.privado = price
                            if not dry_run:
                                existing.save(update_fields=["privado"])
                            updated.append((existing.name, old, price))
                        else:
                            unchanged.append(existing.name)
                    else:
                        simon = _simon_code(simon_raw)
                        svc_type = get_type(default_type_name)
                        if not dry_run:
                            new_svc = Service.objects.create(
                                simon=simon, name=name, type=svc_type,
                                co_pago=price, privado=price,
                            )
                        else:
                            # Unsaved placeholder so a name repeated later in
                            # the same run (a real case: PROCEDIMIENTOS lists
                            # "SUTURAS HERIDAS MULTIPLES Y EN GENERAL" twice,
                            # at two different prices) is correctly previewed
                            # as create-then-update, not double-counted as
                            # two separate creates.
                            new_svc = Service(
                                simon=simon, name=name, type=svc_type,
                                co_pago=price, privado=price,
                            )
                        existing_by_name[key] = new_svc
                        created.append((name, simon, default_type_name, price))

            if dry_run:
                transaction.set_rollback(True)

        if collisions:
            self.stdout.write(self.style.WARNING(f"\nName collisions resolved: {len(collisions)}"))
            for name, prior_type, this_type in collisions:
                self.stdout.write(f"  ? {name}: both [{prior_type}] and [{this_type}] exist -- matched against the non-CONSULTA one")
        self.stdout.write(self.style.SUCCESS(f"\nCreated: {len(created)}"))
        for name, simon, type_name, price in created:
            self.stdout.write(f"  + [{type_name}] {name} (SIMON {simon}) privado={price} co_pago={price}")
        self.stdout.write(self.style.SUCCESS(f"\nUpdated: {len(updated)}"))
        for name, old, new in updated:
            self.stdout.write(f"  ~ {name}: privado {old} -> {new}")
        self.stdout.write(f"\nUnchanged: {len(unchanged)}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"\nSkipped (non-numeric price): {len(skipped)}"))
            for sheet_name, name, raw in skipped:
                self.stdout.write(f"  ! [{sheet_name}] {name}: {raw!r}")
        if deactivated:
            self.stdout.write(self.style.WARNING(f"\nDeactivated (legacy CONSULTA type): {len(deactivated)}"))
            for name in deactivated:
                self.stdout.write(f"  - {name}")
        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run -- no changes were saved."))
