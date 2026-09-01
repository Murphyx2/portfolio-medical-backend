"""Additive demo data for exercising the Servicios Prestados / Paquete ARS
reports (apps/reportes/services/engine.py) end-to-end against the real dev
DB, covering the four ways a service line can be classified:

    - ARS sin programa   (encounter.ars set, ars_program=None, ars_covered=True)
    - ARS con programa   (encounter.ars + ars_program set, ars_covered=True)
    - Particular (flag)  (encounter.ars + ars_program set, but ars_covered=False)
    - Particular (no ARS)(encounter.ars=None entirely)

Usage:
    python manage.py seed_report_demo_data
    python manage.py seed_report_demo_data --month 8 --year 2026 --seed 1

Unlike seed_demo_data (apps/core), this command never deletes anything --
it only creates new Service/Patient/Encounter/EncounterService rows -- so it
carries no --confirm gate and is safe to re-run (each run adds another batch).
"""

import random
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.ars.models import ARS
from apps.centers.models import MedicalCenter
from apps.encounters.models import Encounter, EncounterService
from apps.patients.models import Patient
from apps.services.models import Service, ServiceType

FIRST_NAMES = [
    "Jose", "Luis", "Carlos", "Juan", "Miguel", "Rafael", "Pedro", "Manuel",
    "Francisco", "Antonio", "Maria", "Ana", "Carmen", "Rosa", "Altagracia",
    "Yolanda", "Mercedes", "Francisca", "Juana", "Miguelina",
]
LAST_NAMES = [
    "Perez", "Rodriguez", "Martinez", "Garcia", "Hernandez", "Gonzalez",
    "Lopez", "Diaz", "Reyes", "Cruz", "Ramirez", "Santos", "Peguero",
    "Feliz", "Nunez", "Castillo", "Jimenez", "Vargas", "Guzman",
]
DR_AREA_CODES = ["809", "829", "849"]

# (simon, name, co_pago, privado) -- 10 distinct services shared across all
# four scenarios, per the report's per-service grouping.
SERVICES = [
    ("100001", "Medicina General", "300.00", "800.00"),
    ("100002", "Medicina Familiar", "350.00", "900.00"),
    ("100003", "Pediatria", "400.00", "1000.00"),
    ("100004", "Ginecologia", "450.00", "1100.00"),
    ("100005", "Rayos X", "600.00", "1500.00"),
    ("100006", "Laboratorio Clinico", "250.00", "700.00"),
    ("100007", "Electrocardiograma", "500.00", "1300.00"),
    ("100008", "Curacion", "200.00", "500.00"),
    ("100009", "Nebulizacion", "180.00", "450.00"),
    ("100010", "Sutura", "550.00", "1400.00"),
]


class Command(BaseCommand):
    help = (
        "Create demo Patients/Encounters covering ARS sin programa, ARS con "
        "programa, and both Particular paths (ars_covered=False and no ARS "
        "at all), 10 rows across 10 services each, to exercise the reportes "
        "engine end-to-end. Purely additive -- no --confirm needed."
    )

    def add_arguments(self, parser):
        today = timezone.localdate()
        parser.add_argument("--month", type=int, default=today.month)
        parser.add_argument("--year", type=int, default=today.year)
        parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed.")

    def handle(self, *args, **options):
        month, year = options["month"], options["year"]
        if not 1 <= month <= 12:
            raise CommandError("--month must be between 1 and 12.")

        User = get_user_model()
        admin = User.objects.filter(username="admin").first()
        if admin is None:
            raise CommandError("No 'admin' user found -- run `manage.py create_admin` first.")

        ars_choices = list(
            ARS.objects.filter(ars_id__in=["SM", "SE"]).prefetch_related("programs")
        )
        if not ars_choices or not all(a.programs.exists() for a in ars_choices):
            raise CommandError(
                "Expected seeded ARS SEMMA ('SM') and SENASA ('SE') with programs "
                "-- run migrations first."
            )

        rng = random.Random(options["seed"])

        with transaction.atomic():
            center = self._get_center()
            services = self._get_services()
            # Only tracks cedulas generated within this run (matches
            # seed_demo_data.py's approach) -- real uniqueness against
            # existing patients is enforced by Patient's cedula_hash blind
            # index at save() time; an 11-digit random collision with
            # existing data is astronomically unlikely.
            used_cedulas: set[str] = set()

            counts = {"sin_programa": 0, "con_programa": 0, "particular_flag": 0, "particular_no_ars": 0}
            # Each real ARS (SEMMA, SENASA) gets its own full 10-service
            # sin-programa and con-programa bucket -- not a random split --
            # so every "{ARS} - (sin programa)" / "{ARS} - {programa}" report
            # file has all 10 services represented, not just some of them.
            for ars in ars_choices:
                programa = rng.choice(list(ars.programs.all()))
                for service in services:
                    self._make_encounter(
                        rng, service, center, admin, month, year, used_cedulas,
                        ars=ars, ars_program=None, ars_covered=True,
                    )
                    counts["sin_programa"] += 1

                    self._make_encounter(
                        rng, service, center, admin, month, year, used_cedulas,
                        ars=ars, ars_program=programa, ars_covered=True,
                    )
                    counts["con_programa"] += 1

            for service in services:
                ars = rng.choice(ars_choices)
                self._make_encounter(
                    rng, service, center, admin, month, year, used_cedulas,
                    ars=ars, ars_program=rng.choice(list(ars.programs.all())), ars_covered=False,
                )
                counts["particular_flag"] += 1

                self._make_encounter(
                    rng, service, center, admin, month, year, used_cedulas,
                    ars=None, ars_program=None, ars_covered=True,
                )
                counts["particular_no_ars"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {sum(counts.values())} encounters for {year:04d}-{month:02d} at "
                f"'{center.name}': {counts['sin_programa']} ARS sin programa, "
                f"{counts['con_programa']} ARS con programa, "
                f"{counts['particular_flag']} particular (ars_covered=False), "
                f"{counts['particular_no_ars']} particular (no ARS). "
                f"{len(services)} services used."
            )
        )

    def _get_center(self) -> MedicalCenter:
        center = MedicalCenter.objects.filter(code="INCAF").first()
        if center:
            return center
        return MedicalCenter.objects.get_or_create(
            code="DEMO",
            defaults={"name": "Centro Demo", "address": "Calle Demo #1", "phone": "8095550000"},
        )[0]

    def _get_services(self) -> list[Service]:
        service_type, _ = ServiceType.objects.get_or_create(name="CONSULTA")
        services = []
        for simon, name, co_pago, privado in SERVICES:
            service, _ = Service.objects.get_or_create(
                simon=simon,
                defaults={"name": name, "type": service_type, "co_pago": co_pago, "privado": privado},
            )
            services.append(service)
        return services

    def _make_encounter(
        self, rng, service, center, created_by, month, year, used_cedulas,
        *, ars, ars_program, ars_covered,
    ):
        patient = self._make_patient(rng, used_cedulas, ars=ars, ars_program=ars_program)
        completed_at = self._random_datetime_in_month(rng, year, month)
        encounter = Encounter.objects.create(
            service_type=service.type,
            patient=patient,
            center=center,
            status=Encounter.Status.COMPLETED,
            completed_at=completed_at,
            created_by=created_by,
            ars=ars,
            ars_program=ars_program,
        )
        EncounterService.objects.create(
            encounter=encounter,
            service=service,
            quantity=rng.randint(1, 3),
            status=EncounterService.Status.COMPLETED,
            ars_covered=ars_covered,
        )
        return encounter

    def _make_patient(self, rng, used_cedulas, *, ars, ars_program) -> Patient:
        first = rng.choice(FIRST_NAMES)
        last = f"{rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}"
        cedula = self._unique_digits(rng, 11, used_cedulas)
        birth_date = date(1950, 1, 1) + timedelta(days=rng.randint(0, 25000))
        return Patient.objects.create(
            first_name=first,
            last_name=last,
            birth_date=birth_date.isoformat(),
            gender=rng.choice([Patient.Gender.MALE, Patient.Gender.FEMALE]),
            phone=f"{rng.choice(DR_AREA_CODES)}{rng.randint(1000000, 9999999)}",
            cedula=cedula,
            ars=ars,
            ars_program=ars_program,
        )

    @staticmethod
    def _random_datetime_in_month(rng: random.Random, year: int, month: int):
        day = rng.randint(1, 28)
        naive = date(year, month, day)
        return timezone.make_aware(
            timezone.datetime(naive.year, naive.month, naive.day, rng.randint(8, 17), rng.randint(0, 59))
        )

    @staticmethod
    def _unique_digits(rng: random.Random, length: int, used: set[str]) -> str:
        while True:
            digits = "".join(str(rng.randint(0, 9)) for _ in range(length))
            if digits not in used:
                used.add(digits)
                return digits
