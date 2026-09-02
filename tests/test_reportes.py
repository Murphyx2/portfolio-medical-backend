"""Reportes module: RBAC (view=admin/it/center_manager only, edit
definitions=admin/it only), center-manager generate is locked to their own
assigned center, the Servicios prestados engine (COMPLETED-only, month
fallback to created_at, ARS/Programa grouping and labels, Cant/Precio/Valor),
the Paquete ARS pack (skips empty ARS x Programa slices), and audit logging
on generate.
"""

import io
import zipfile
from decimal import Decimal

from django.utils import timezone
from openpyxl import load_workbook

from apps.ars.models import ARS, ARSProgram
from apps.centers.models import MedicalCenter
from apps.core.models import AuditLog
from apps.encounters.models import Encounter, EncounterService
from apps.patients.models import Patient
from apps.reportes.models import ReportDefinition
from apps.reportes.services.engine import ServiceLine, ars_program_label, servicios_prestados_rows
from apps.reportes.services.excel import build_pack_zip, build_servicios_prestados_workbook
from apps.services.models import Service, ServiceType


def _center(code="C1"):
    return MedicalCenter.objects.create(name=f"Center {code}", code=code, address="A", phone="1")


def _ars(name="SENASA"):
    # apps/ars/migrations/0002_seed_defaults.py already seeds SENASA/SEMMA
    # with their real programs -- reuse those rather than colliding with the
    # unique ARS.name constraint.
    return ARS.objects.get(name=name)


def _program(ars, name="SENASA Contigo"):
    return ARSProgram.objects.get(ars=ars, name=name)


def _patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "birth_date": "1990-01-01",
        "cedula": overrides.pop("cedula", "00100000001"),
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _service(**overrides):
    service_type, _ = ServiceType.objects.get_or_create(name="CONSULTA")
    data = {
        "simon": "123456",
        "name": "Consulta general",
        "type": service_type,
        "co_pago": "500.00",
        "privado": "1000.00",
    }
    data.update(overrides)
    return Service.objects.create(**data)


def _completed_encounter(
    *, patient, center, created_by, completed_at, service, quantity=1,
    ars=None, ars_program=None, ars_covered=True,
):
    service_type, _ = ServiceType.objects.get_or_create(name="CONSULTA")
    encounter = Encounter.objects.create(
        service_type=service_type,
        patient=patient,
        center=center,
        status=Encounter.Status.COMPLETED,
        completed_at=completed_at,
        created_by=created_by,
        ars=ars,
        ars_program=ars_program,
    )
    EncounterService.objects.create(
        encounter=encounter, service=service, quantity=quantity,
        status=EncounterService.Status.COMPLETED, ars_covered=ars_covered,
    )
    return encounter


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_receptionist_doctor_nurse_cannot_view_reportes(
    auth_client, receptionist_user, doctor_user, nurse_user
):
    for user in (receptionist_user, doctor_user, nurse_user):
        res = auth_client(user).get("/api/reportes/definiciones/")
        assert res.status_code == 403, user.role


def test_admin_it_center_manager_can_view_reportes(
    auth_client, admin_user, it_user, center_manager_user
):
    for user in (admin_user, it_user, center_manager_user):
        res = auth_client(user).get("/api/reportes/definiciones/")
        assert res.status_code == 200, (user.role, res.data)


def test_only_admin_it_can_edit_definitions(auth_client, admin_user, it_user, center_manager_user):
    definition = ReportDefinition.objects.get(engine_key="servicios_prestados")
    res = auth_client(center_manager_user).patch(
        f"/api/reportes/definiciones/{definition.id}/", {"description": "nope"}
    )
    assert res.status_code == 403

    res = auth_client(it_user).patch(
        f"/api/reportes/definiciones/{definition.id}/", {"description": "updated"}
    )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Center-manager generate is locked to their own assigned center
# ---------------------------------------------------------------------------


def test_center_manager_without_assigned_center_gets_400(auth_client, center_manager_user):
    definition = ReportDefinition.objects.get(engine_key="servicios_prestados")
    res = auth_client(center_manager_user).post(
        f"/api/reportes/definiciones/{definition.id}/generar/", {"mes": "2026-07"}
    )
    assert res.status_code == 400


def test_center_manager_is_forced_to_own_center(auth_client, make_user):
    from apps.accounts.models import User

    own_center = _center("OWN")
    other_center = _center("OTHER")
    cm = make_user("cm2", User.Role.CENTER_MANAGER, center=own_center)

    patient = _patient(center=other_center)
    service = _service()
    _completed_encounter(
        patient=patient, center=other_center, created_by=cm, completed_at=timezone.now(), service=service
    )

    definition = ReportDefinition.objects.get(engine_key="servicios_prestados")
    res = auth_client(cm).post(
        f"/api/reportes/definiciones/{definition.id}/generar/",
        {"mes": timezone.now().strftime("%Y-%m"), "centro": other_center.id},
    )
    assert res.status_code == 200
    wb = load_workbook(io.BytesIO(res.content))
    ws = wb.active
    # No data in own_center for this patient (encounter is in other_center),
    # so beyond the cover rows there should be no service line -- only the
    # Total row.
    rows = list(ws.iter_rows(values_only=True))
    assert rows[3][0] == own_center.name  # Centro cover row forced to own center


# ---------------------------------------------------------------------------
# Engine correctness
# ---------------------------------------------------------------------------


def test_engine_counts_only_completed_encounters(admin_user):
    center = _center()
    patient = _patient(ars=None)
    service = _service(co_pago="500.00")
    service_type, _ = ServiceType.objects.get_or_create(name="CONSULTA")
    now = timezone.localtime(timezone.now())

    _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=now, service=service, quantity=2
    )
    # DRAFT and CANCELLED encounters must not count.
    Encounter.objects.create(
        service_type=service_type, patient=patient, center=center, status=Encounter.Status.DRAFT,
        created_by=admin_user,
    )
    cancelled = Encounter.objects.create(
        service_type=service_type, patient=patient, center=center, status=Encounter.Status.CANCELLED,
        created_by=admin_user,
    )
    EncounterService.objects.create(encounter=cancelled, service=service, quantity=5)

    rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert len(rows) == 1
    assert rows[0].cant == 2
    assert rows[0].precio == Decimal("500.00")
    assert rows[0].valor == Decimal("1000.00")


def test_engine_falls_back_to_created_at_when_completed_at_is_null(admin_user):
    center = _center()
    patient = _patient(ars=None)
    service = _service()
    service_type, _ = ServiceType.objects.get_or_create(name="CONSULTA")
    encounter = Encounter.objects.create(
        service_type=service_type, patient=patient, center=center, status=Encounter.Status.COMPLETED,
        created_by=admin_user,
    )
    EncounterService.objects.create(encounter=encounter, service=service, quantity=1)
    encounter.refresh_from_db()
    now = timezone.localtime(timezone.now())

    rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert len(rows) == 1


def test_engine_month_range_rolls_over_december_into_next_year(admin_user):
    # Regression for the sargable date-range rewrite: December must bound to
    # [Dec 1, Jan 1 of year+1), not silently exclude everything after month=12.
    center = _center()
    patient = _patient(ars=None)
    service = _service()
    dec_31 = timezone.make_aware(timezone.datetime(2026, 12, 31, 23, 0))
    jan_1_next_year = timezone.make_aware(timezone.datetime(2027, 1, 1, 0, 30))

    _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=dec_31, service=service
    )
    # Just past the boundary -- must NOT be counted in December's report.
    _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=jan_1_next_year, service=service
    )

    rows = servicios_prestados_rows(
        year=2026, month=12, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert len(rows) == 1
    assert rows[0].cant == 1


def test_engine_uses_encounterservice_co_pago_snapshot_not_flat_service_price(admin_user):
    """The engine must price each line off its own EncounterService.co_pago
    snapshot (see apps.services.services.resolve_line_price), not the flat
    Service.co_pago -- two lines for the same service can have been billed
    at different resolved prices (e.g. an ARS override changed mid-period)."""
    center = _center()
    patient = _patient(ars=None)
    service = _service(co_pago="500.00")
    service_type, _ = ServiceType.objects.get_or_create(name="CONSULTA")
    now = timezone.localtime(timezone.now())

    for co_pago in (Decimal("300.00"), Decimal("400.00")):
        encounter = Encounter.objects.create(
            service_type=service_type, patient=patient, center=center,
            status=Encounter.Status.COMPLETED, completed_at=now, created_by=admin_user,
        )
        EncounterService.objects.create(
            encounter=encounter, service=service, quantity=1,
            status=EncounterService.Status.COMPLETED, ars_covered=True, co_pago=co_pago,
        )

    rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert len(rows) == 1
    assert rows[0].cant == 2
    assert rows[0].valor == Decimal("700.00")
    assert rows[0].precio == Decimal("350.00")


def test_engine_falls_back_to_service_co_pago_when_snapshot_missing(admin_user):
    """Rows predating the co_pago snapshot (co_pago IS NULL, e.g. missed by
    the backfill migration) must still price off the flat Service.co_pago,
    not silently drop out of the report or price as zero."""
    center = _center()
    patient = _patient(ars=None)
    service = _service(co_pago="500.00")
    now = timezone.localtime(timezone.now())

    _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=now, service=service
    )
    rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert len(rows) == 1
    assert rows[0].precio == Decimal("500.00")


def test_ars_program_labels(db):
    ars = _ars("SENASA")
    programa = _program(ars, "SENASA Contigo")
    assert ars_program_label(ars, programa) == "SENASA - SENASA Contigo"
    assert ars_program_label(ars, None) == "SENASA - (sin programa)"
    assert ars_program_label(None, None) == "Particular - (sin programa)"


def test_engine_groups_by_ars_and_programa(admin_user):
    center = _center()
    ars = _ars("SENASA")
    programa = _program(ars, "SENASA Contigo")
    covered_patient = _patient(ars=ars, ars_program=programa, cedula="00300000003")
    uncovered_patient = _patient(ars=None, cedula="00400000004")
    service = _service()
    now = timezone.localtime(timezone.now())
    _completed_encounter(
        patient=covered_patient, center=center, created_by=admin_user, completed_at=now, service=service,
        ars=ars, ars_program=programa,
    )
    _completed_encounter(
        patient=uncovered_patient, center=center, created_by=admin_user, completed_at=now, service=service
    )

    covered_rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=ars.id, programa_id=programa.id, centro_id=center.id
    )
    uncovered_rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert len(covered_rows) == 1
    assert len(uncovered_rows) == 1


def test_engine_uses_per_service_ars_covered_flag(admin_user):
    # One ARS-bound encounter, two service lines: one billed under the ARS,
    # one explicitly marked ars_covered=False (e.g. Rayos X not covered even
    # though Medicina familiar is). The uncovered line must fall into
    # Particular, not the patient's/encounter's ARS slice.
    center = _center()
    ars = _ars("SENASA")
    programa = _program(ars, "SENASA Contigo")
    patient = _patient(ars=ars, ars_program=programa, cedula="00900000009")
    covered_service = _service(name="Medicina familiar")
    uncovered_service = _service(name="Rayos X", simon="999999")
    now = timezone.localtime(timezone.now())

    encounter = _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=now,
        service=covered_service, ars=ars, ars_program=programa,
    )
    EncounterService.objects.create(
        encounter=encounter, service=uncovered_service, quantity=1,
        status=EncounterService.Status.COMPLETED, ars_covered=False,
    )

    covered_rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=ars.id, programa_id=programa.id, centro_id=center.id
    )
    particular_rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert [row.name for row in covered_rows] == ["MEDICINA FAMILIAR"]
    assert [row.name for row in particular_rows] == ["RAYOS X"]


def test_engine_encounter_without_ars_is_particular_regardless_of_ars_covered(admin_user):
    # An encounter with no ARS at all must land fully in Particular, even if
    # its lines are (harmlessly) marked ars_covered=True.
    center = _center()
    patient = _patient(ars=None, cedula="01000000010")
    service = _service()
    now = timezone.localtime(timezone.now())
    _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=now, service=service,
        ars_covered=True,
    )

    particular_rows = servicios_prestados_rows(
        year=now.year, month=now.month, ars_id=None, programa_id=None, centro_id=center.id
    )
    assert len(particular_rows) == 1


# ---------------------------------------------------------------------------
# Pack: skips empty slices, one xlsx per non-empty ARS x Programa
# ---------------------------------------------------------------------------


def test_pack_skips_empty_slices_and_names_files(admin_user):
    center = _center()
    ars = _ars("SENASA")
    programa = _program(ars, "SENASA Contigo")
    patient = _patient(ars=ars, ars_program=programa, cedula="00200000002")
    service = _service()
    now = timezone.localtime(timezone.now())
    _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=now, service=service,
        ars=ars, ars_program=programa,
    )

    zip_bytes = build_pack_zip(
        year=now.year, month=now.month, centro_id=center.id, centro_name=center.name, user=admin_user
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert len(names) == 1
    assert names[0] == f"SENASA - SENASA Contigo - {now.year:04d}-{now.month:02d}.xlsx"


def test_pack_collapses_multiple_patients_sharing_the_same_slice(admin_user):
    # Regression test: EncounterService's default `ordering = ["id"]` used to
    # leak into distinct_ars_program_slices()'s .values_list().distinct(),
    # making every row "distinct" (since id always differs) instead of
    # collapsing by (ars_id, ars_program_id) -- a pack with 2 patients and 2
    # service lines under the same ARS+Programa produced 2 duplicate xlsx
    # files instead of 1.
    center = _center()
    ars = _ars("SENASA")
    programa = _program(ars, "SENASA Contigo")
    service_a = _service(name="Consulta A")
    service_b = _service(name="Consulta B", simon="654321")
    now = timezone.localtime(timezone.now())
    patient_1 = _patient(ars=ars, ars_program=programa, cedula="00500000005")
    patient_2 = _patient(ars=ars, ars_program=programa, cedula="00600000006")
    _completed_encounter(
        patient=patient_1, center=center, created_by=admin_user, completed_at=now, service=service_a,
        ars=ars, ars_program=programa,
    )
    _completed_encounter(
        patient=patient_2, center=center, created_by=admin_user, completed_at=now, service=service_b,
        ars=ars, ars_program=programa,
    )

    zip_bytes = build_pack_zip(
        year=now.year, month=now.month, centro_id=center.id, centro_name=center.name, user=admin_user
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
    assert names == [f"SENASA - SENASA Contigo - {now.year:04d}-{now.month:02d}.xlsx"]


def test_pack_automatically_includes_a_brand_new_ars_with_no_code_change(admin_user):
    # distinct_ars_program_slices() derives every slice from real patient
    # data (Patient.ars_id/ars_program_id), not a hardcoded ARS list -- a
    # brand-new ARS + program created ad hoc (not from the seed migration)
    # must get its own file automatically, and an ARS with no program at all
    # must produce its own "(sin programa)" file, same as the seeded ones.
    center = _center()
    new_ars = ARS.objects.create(ars_id="ZZ", name="ARS Nueva De Prueba")
    new_program = ARSProgram.objects.create(ars=new_ars, name="Programa Nuevo")
    service = _service()
    now = timezone.localtime(timezone.now())

    patient_with_program = _patient(ars=new_ars, ars_program=new_program, cedula="00700000007")
    patient_without_program = _patient(ars=new_ars, ars_program=None, cedula="00800000008")
    _completed_encounter(
        patient=patient_with_program, center=center, created_by=admin_user, completed_at=now, service=service,
        ars=new_ars, ars_program=new_program,
    )
    _completed_encounter(
        patient=patient_without_program, center=center, created_by=admin_user, completed_at=now, service=service,
        ars=new_ars,
    )

    zip_bytes = build_pack_zip(
        year=now.year, month=now.month, centro_id=center.id, centro_name=center.name, user=admin_user
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
    assert names == {
        f"ARS Nueva De Prueba - Programa Nuevo - {now.year:04d}-{now.month:02d}.xlsx",
        f"ARS Nueva De Prueba - (sin programa) - {now.year:04d}-{now.month:02d}.xlsx",
    }


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_generate_writes_audit_log(auth_client, admin_user):
    center = _center()
    patient = _patient(center=center, ars=None)
    service = _service()
    now = timezone.localtime(timezone.now())
    _completed_encounter(
        patient=patient, center=center, created_by=admin_user, completed_at=now, service=service
    )
    definition = ReportDefinition.objects.get(engine_key="servicios_prestados")

    res = auth_client(admin_user).post(
        f"/api/reportes/definiciones/{definition.id}/generar/",
        {"mes": now.strftime("%Y-%m"), "centro": center.id},
    )
    assert res.status_code == 200
    assert AuditLog.objects.filter(
        action=AuditLog.Action.EXPORT, target_type="ReportDefinition", target_id=definition.id
    ).exists()


# ---------------------------------------------------------------------------
# XLSX formula-injection sanitization
# ---------------------------------------------------------------------------


def test_service_name_starting_with_formula_char_is_sanitized(admin_user):
    # A service name like "=SUM(A1:A9)" (creatable by anyone with edit rights
    # on the Service reference list) must never land as a live formula in a
    # generated workbook -- Excel evaluates a leading =/+/-/@ on open.
    rows = [ServiceLine(name="=SUM(A1:A9)", cant=1, precio=Decimal("100.00"), valor=Decimal("100.00"))]
    wb = build_servicios_prestados_workbook(
        rows=rows, label="Particular - (sin programa)", year=2026, month=1, centro_name=None, user=admin_user
    )
    buffer = io.BytesIO()
    wb.save(buffer)
    reloaded = load_workbook(buffer)
    ws = reloaded.active
    data_row = [row for row in ws.iter_rows(min_row=8, max_col=2, values_only=True) if row[0] == 1][0]
    name_cell = data_row[1]
    assert name_cell == "'=SUM(A1:A9)"
    assert not str(name_cell).startswith("=SUM")
