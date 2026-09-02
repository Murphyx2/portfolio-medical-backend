"""Upsert ServicePrice (per-ARS / per-ARS+Program Co-pago overrides) from a
JSON data file -- see apps/services/management/data/ for examples.

Usage:
    python manage.py import_ars_service_prices --file <path/to/data.json> [--dry-run]

JSON shape:
    {
      "create_services": [
        {"name": "...", "simon": "0000", "type": "ADMISION", "co_pago": "0.00", "privado": "0.00"}
      ],
      "prices": [
        {"service": "<exact Service.name>", "ars": "<exact ARS.name>",
         "program": "<exact ARSProgram.name>" | null, "co_pago": "750.00"}
      ]
    }

`create_services` entries are only created if no Service with that
(normalized) name already exists -- safe to leave them in the file on a
re-run. `prices` entries are upserted by (service, ars, ars_program) via
update_or_create, so re-running with an unchanged file is a no-op and
re-running after editing a price updates it in place; a soft-deleted
ServicePrice matching the same key is reactivated rather than duplicated
(ServicePrice's uniqueness is enforced by a DB constraint that isn't
active-aware).

Matching for `service`/`ars`/`program` is by exact name (case-sensitive)
against *active* rows only -- these names are meant to be copy-pasted from
the Services/ARS pages, not fuzzy-guessed, since a silent near-match would
attach a price to the wrong service. An inactive/soft-deleted Service with
the same name is never matched, so a deactivated legacy duplicate can't
silently steal a price meant for the real one.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ars.models import ARS, ARSProgram
from apps.services.models import Service, ServicePrice, ServiceType


class Command(BaseCommand):
    help = "Upsert ServicePrice rows (per-ARS / per-ARS+Program Co-pago overrides) from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the price-data .json file")
        parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")

    def handle(self, *args, **options):
        path = options["file"]
        dry_run = options["dry_run"]
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            raise CommandError(f"File not found: {path}")
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}")

        created_services, upserted, unchanged, errors = [], [], [], []
        # Services created in this same run (real or, in dry-run, an unsaved
        # placeholder) so a `prices` entry targeting one of them previews
        # correctly instead of erroring "not found" just because dry-run
        # never persisted it.
        new_services_by_name: dict[str, Service] = {}

        with transaction.atomic():
            for entry in data.get("create_services", []):
                name = entry["name"].strip().upper()
                if Service.all_objects.filter(name=name).exists():
                    continue
                # Case-insensitive lookup before create -- some pre-existing
                # ServiceTypes were seeded without the uppercase
                # normalization ServiceType.save() otherwise enforces, so a
                # naive get_or_create(name=upper()) can silently create a
                # duplicate all-caps type instead of reusing the real one.
                type_name = entry["type"].strip()
                svc_type = ServiceType.objects.filter(name__iexact=type_name).first()
                if svc_type is None:
                    svc_type = ServiceType.objects.create(name=type_name.upper())
                if not dry_run:
                    svc = Service.objects.create(
                        simon=entry["simon"], name=name, type=svc_type,
                        co_pago=Decimal(entry["co_pago"]), privado=Decimal(entry["privado"]),
                    )
                else:
                    svc = Service(
                        simon=entry["simon"], name=name, type=svc_type,
                        co_pago=Decimal(entry["co_pago"]), privado=Decimal(entry["privado"]),
                    )
                new_services_by_name[name] = svc
                created_services.append(name)

            for entry in data.get("prices", []):
                service_name = entry["service"]
                ars_name = entry["ars"]
                program_name = entry.get("program")
                try:
                    price = Decimal(str(entry["co_pago"])).quantize(Decimal("0.01"))
                except InvalidOperation:
                    errors.append(f"{service_name} / {ars_name}: invalid co_pago {entry['co_pago']!r}")
                    continue

                service = Service.objects.filter(name=service_name).first() or new_services_by_name.get(
                    service_name.strip().upper()
                )
                if service is None:
                    errors.append(f"Service not found (or only inactive matches exist): {service_name!r}")
                    continue
                ars = ARS.objects.filter(name=ars_name).first()
                if ars is None:
                    errors.append(f"ARS not found: {ars_name!r}")
                    continue
                program = None
                if program_name is not None:
                    program = ARSProgram.objects.filter(ars=ars, name=program_name).first()
                    if program is None:
                        errors.append(f"ARSProgram not found for {ars_name!r}: {program_name!r}")
                        continue

                # A brand-new (unsaved, dry-run-only) service obviously has
                # no existing ServicePrice yet -- and Django refuses an
                # unsaved instance in a related filter anyway.
                existing = (
                    ServicePrice.all_objects.filter(service=service, ars=ars, ars_program=program).first()
                    if service.pk is not None
                    else None
                )
                if existing is not None and existing.co_pago == price and existing.active:
                    unchanged.append((service.name, ars.name, program_name))
                    continue

                label = f"{service.name} @ {ars.name}" + (f" / {program_name}" if program_name else "")
                if not dry_run:
                    ServicePrice.all_objects.update_or_create(
                        service=service, ars=ars, ars_program=program,
                        defaults={"co_pago": price, "active": True},
                    )
                upserted.append((label, price))

            if dry_run:
                transaction.set_rollback(True)

        if created_services:
            self.stdout.write(self.style.SUCCESS(f"\nCreated services: {len(created_services)}"))
            for name in created_services:
                self.stdout.write(f"  + {name}")
        self.stdout.write(self.style.SUCCESS(f"\nUpserted prices: {len(upserted)}"))
        for label, price in upserted:
            self.stdout.write(f"  ~ {label}: {price}")
        self.stdout.write(f"\nUnchanged: {len(unchanged)}")
        if errors:
            self.stdout.write(self.style.ERROR(f"\nErrors: {len(errors)}"))
            for err in errors:
                self.stdout.write(f"  ! {err}")
        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run -- no changes were saved."))
