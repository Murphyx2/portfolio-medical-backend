"""Wipe and regenerate demo data that satisfies current business rules.

Usage:
    python manage.py seed_demo_data --confirm
    python manage.py seed_demo_data --confirm --patients 50 --records 5

For now this only covers Patients + Records (the two things prone to
accumulating rule-breaking junk from repeated QA-script runs against the dev
stack -- e.g. duplicate/reused cedula and NSS values). It's written as a
reusable demo-data generator, not a one-off script: covering the remaining
pages (centers/doctors/medicines/appointments/ars) later is a matter of
adding more sections to this same command.

Deletes every Patient row (a real DB delete, not the soft-delete the API
uses -- see apps/core/mixins.py) which cascades away every MedicalRecord,
ConsultationLog, RecordImage, and Appointment tied to those patients too,
then creates fresh patients (unique cedula always, unique NSS when present)
and medical records against them.
"""

import random
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ars.models import ARS
from apps.patients.models import Patient, PatientGuardian
from apps.records.models import MedicalRecord

FIRST_NAMES = [
    "Jose", "Luis", "Carlos", "Juan", "Miguel", "Rafael", "Pedro", "Manuel",
    "Francisco", "Antonio", "Ramon", "Julio", "Victor", "Wilson", "Ruben",
    "Maria", "Ana", "Carmen", "Rosa", "Altagracia", "Yolanda", "Mercedes",
    "Francisca", "Juana", "Miguelina", "Yesenia", "Dulce", "Esperanza",
    "Elena", "Patricia",
]
LAST_NAMES = [
    "Perez", "Rodriguez", "Martinez", "Garcia", "Hernandez", "Gonzalez",
    "Lopez", "Diaz", "Reyes", "Cruz", "Ramirez", "Santos", "Mercedes",
    "Peguero", "Feliz", "Nunez", "Castillo", "Jimenez", "Vargas", "Guzman",
]
STREETS = [
    "Calle Duarte", "Av. 27 de Febrero", "Calle El Sol", "Av. Independencia",
    "Calle Restauracion", "Av. Winston Churchill", "Calle Mella",
    "Calle Padre Billini", "Av. Maximo Gomez", "Calle Las Flores",
]
RECORD_TITLES = [
    "Consulta general", "Control", "Chequeo anual", "Consulta de seguimiento",
    "Evaluacion inicial", "Consulta de emergencia", "Control de rutina",
    "Consulta pediatrica", "Consulta de especialidad", "Revision post-tratamiento",
]

DR_AREA_CODES = ["809", "829", "849"]

# Fraction of patients over 50 who get an ARS/program on file -- "some", not
# all, matches the NSS fill-rate pattern below and reflects that not every
# older patient has active insurance.
ARS_ASSIGNMENT_PROBABILITY = 0.6
ARS_MIN_AGE = 50


class Command(BaseCommand):
    help = "Wipe and regenerate demo Patients + Records that satisfy current business rules."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required -- confirms you want to delete all existing Patient/Record data.",
        )
        parser.add_argument("--patients", type=int, default=75)
        parser.add_argument("--records", type=int, default=10)
        parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed.")

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError(
                "Refusing to run without --confirm (this deletes all Patient/"
                "MedicalRecord/ConsultationLog/RecordImage/Appointment data)."
            )
        n_patients = options["patients"]
        n_records = options["records"]
        if n_records > n_patients:
            raise CommandError("--records cannot exceed --patients.")

        User = get_user_model()
        admin = User.objects.filter(username="admin").first()
        if admin is None:
            raise CommandError(
                "No 'admin' user found -- run `manage.py create_admin` first."
            )

        rng = random.Random(options["seed"])

        with transaction.atomic():
            deleted_patients = Patient.all_objects.count()
            Patient.all_objects.all().delete()

            patients = self._create_patients(rng, n_patients)
            records = self._create_records(rng, patients[:n_records], admin)

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_patients} patients (cascaded to their records/logs/"
                f"appointments). Created {len(patients)} patients, {len(records)} records."
            )
        )

    def _create_patients(self, rng: random.Random, count: int) -> list[Patient]:
        used_cedulas: set[str] = set()
        used_nss: set[str] = set()
        # Real seeded insurers (SEMMA/SENASA, per PROGRESS.md) with at least
        # one program -- excludes the QA/RBAC-script ARS clutter that
        # accumulates in this table (matches this file's own reason for
        # existing: undo QA-script junk, don't propagate it into fresh data).
        ars_choices = [
            a for a in ARS.objects.filter(ars_id__in=["SM", "SE"]).prefetch_related("programs")
            if a.programs.exists()
        ]
        patients = []
        for _ in range(count):
            first = rng.choice(FIRST_NAMES)
            last = f"{rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}"
            cedula = self._unique_digits(rng, 11, used_cedulas)
            nss = self._unique_digits(rng, 11, used_nss) if rng.random() < 0.7 else ""
            birth_date = date(1940, 1, 1) + timedelta(days=rng.randint(0, 30000))
            patient_kwargs = dict(
                first_name=first,
                last_name=last,
                birth_date=birth_date.isoformat(),
                gender=rng.choice([Patient.Gender.MALE, Patient.Gender.FEMALE]),
                phone=f"{rng.choice(DR_AREA_CODES)}{rng.randint(1000000, 9999999)}",
                address=f"{rng.choice(STREETS)} #{rng.randint(1, 200)}",
                email=f"{first.lower()}.{last.split()[0].lower()}{rng.randint(1, 999)}@example.com",
                cedula=cedula,
                nss=nss,
            )
            age = self._age(birth_date)
            is_minor = age < 18
            if not is_minor and age > ARS_MIN_AGE and ars_choices and rng.random() < ARS_ASSIGNMENT_PROBABILITY:
                patient_kwargs.update(self._ars_kwargs(rng, ars_choices))
            patient = Patient.objects.create(**patient_kwargs)
            if is_minor:
                PatientGuardian.objects.create(patient=patient, **self._guardian_kwargs(rng))
            patients.append(patient)
        return patients

    @staticmethod
    def _ars_kwargs(rng: random.Random, ars_choices: list[ARS]) -> dict:
        ars = rng.choice(ars_choices)
        programs = list(ars.programs.all())
        return {"ars": ars, "ars_program": rng.choice(programs) if programs else None}

    def _guardian_kwargs(self, rng: random.Random) -> dict:
        """Synthetic PatientGuardian fields for a minor patient (no
        uniqueness needed -- siblings can legitimately share a guardian)."""
        return {
            "first_name": rng.choice(FIRST_NAMES),
            "last_name": f"{rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}",
            "cedula": "".join(str(rng.randint(0, 9)) for _ in range(11)),
            "nss": (
                "".join(str(rng.randint(0, 9)) for _ in range(11)) if rng.random() < 0.5 else ""
            ),
            "phone": f"{rng.choice(DR_AREA_CODES)}{rng.randint(1000000, 9999999)}",
        }

    @staticmethod
    def _age(birth_date: date) -> int:
        today = date.today()
        return (
            today.year
            - birth_date.year
            - ((today.month, today.day) < (birth_date.month, birth_date.day))
        )

    def _create_records(
        self, rng: random.Random, patients: list[Patient], created_by
    ) -> list[MedicalRecord]:
        records = []
        for patient in patients:
            records.append(
                MedicalRecord.objects.create(
                    patient=patient,
                    created_by=created_by,
                    title=rng.choice(RECORD_TITLES),
                    diagnosis="Sin hallazgos significativos.",
                    treatment="Reposo y seguimiento en consulta de control.",
                    notes="Registro generado por seed_demo_data.",
                )
            )
        return records

    @staticmethod
    def _unique_digits(rng: random.Random, length: int, used: set[str]) -> str:
        while True:
            digits = "".join(str(rng.randint(0, 9)) for _ in range(length))
            if digits not in used:
                used.add(digits)
                return digits
