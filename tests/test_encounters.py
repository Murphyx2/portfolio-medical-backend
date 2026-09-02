"""Encounters module: RBAC (read=all staff, write=admin/doctor/receptionist/
nurse/center_manager, IT read-only), doctor object-level scoping (own
encounters only -- ownership means assigned to at least one service line),
DRAFT->ACTIVE->COMPLETED/CANCELLED status lifecycle via the admit/cancel/
complete actions, encounter_number assignment on admit, same-day-active-
encounter conflict detection with override, primary-diagnosis requirement
(unless the ServiceType is exempted), the at-least-one-service requirement,
the per-service-line requires_doctor conditional doctor requirement, and
clinical-text/PII masking.

Encounter.service_type is the same `apps.services.ServiceType` catalog the
Services page manages (merged from the former, now-deleted EncounterType).

Doctor and room are per-service-line (`EncounterService.doctor`/`.room`),
not on Encounter itself -- a visit can mix several doctors/rooms across its
service lines (see the Encounter form's redesign notes in PROGRESS.md).
"""

import pytest

from apps.centers.models import MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.encounters.models import Encounter
from apps.patients.models import Patient
from apps.rooms.models import Room, RoomType
from apps.services.models import Service, ServiceType


def _center(code="C1"):
    return MedicalCenter.objects.create(name=f"Center {code}", code=code, address="A", phone="1")


def _room(center=None, code="R1"):
    room_type = RoomType.objects.get_or_create(name="CONSULTA")[0]
    return Room.objects.create(
        code=code, name="Room", room_type=room_type, center=center or _center()
    )


def _service_type(name="Consulta General", requires_doctor=False):
    # get_or_create()'s `defaults` only applies on insert -- explicitly sync
    # the flag on every call so a test overriding it for an already-seeded
    # name actually takes effect instead of silently keeping the prior value.
    service_type, _ = ServiceType.objects.get_or_create(name=name.upper())
    if service_type.requires_doctor != requires_doctor:
        service_type.requires_doctor = requires_doctor
        service_type.save()
    return service_type


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


def _doctor(user, **overrides):
    data = {
        "license_number": f"LIC-{user.id}",
        "contact_phone": "8095550000",
    }
    data.update(overrides)
    return DoctorProfile.objects.create(user=user, **data)


def _service(service_type=None, **overrides):
    data = {
        "simon": "123456",
        "name": "Consulta",
        "type": service_type or _service_type(),
        "co_pago": "0",
        "privado": "0",
    }
    data.update(overrides)
    return Service.objects.create(**data)


def _encounter(patient, created_by, *, doctor=None, room=None, service_type=None, **overrides):
    """Model-level helper: an Encounter plus one EncounterService line
    carrying doctor/room (both now line-level, not on Encounter itself)."""
    service_type = service_type or _service_type()
    encounter = Encounter.objects.create(
        service_type=service_type, patient=patient, created_by=created_by, **overrides
    )
    encounter.services.create(service=_service(service_type=service_type), doctor=doctor, room=room)
    return encounter


def _payload(patient, doctor=None, room=None, **overrides):
    service_type_id = overrides.pop("service_type_id", None)
    service_type = (
        ServiceType.objects.get(pk=service_type_id) if service_type_id else _service_type()
    )
    services = overrides.pop("services", None)
    if services is None:
        line = {"service": _service(service_type=service_type).id, "quantity": 1}
        if doctor is not None:
            line["doctor"] = doctor.id
        if room is not None:
            line["room"] = room.id
        services = [line]
    data = {
        "service_type": service_type.id,
        "patient": patient.id,
        "chief_complaint": "Fever",
        "services": services,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# RBAC: read=all staff, write=admin/doctor/receptionist/nurse/center_manager,
# IT is read-only.
# ---------------------------------------------------------------------------


def test_every_role_can_read_encounters(
    auth_client, admin_user, doctor_user, receptionist_user, it_user, nurse_user,
    center_manager_user,
):
    doctor = _doctor(doctor_user)
    patient = _patient()
    _encounter(patient, admin_user, doctor=doctor)
    for user in (
        admin_user, doctor_user, receptionist_user, it_user, nurse_user, center_manager_user,
    ):
        res = auth_client(user).get("/api/encounters/")
        assert res.status_code == 200, (user.role, res.data)


def test_admin_doctor_receptionist_nurse_center_manager_can_create(
    auth_client, admin_user, doctor_user, receptionist_user, nurse_user, center_manager_user,
):
    doctor = _doctor(doctor_user)
    for user in (admin_user, receptionist_user, nurse_user, center_manager_user):
        patient = _patient(cedula=f"0010000{user.id:04d}")
        res = auth_client(user).post(
            "/api/encounters/", _payload(patient, doctor), format="json"
        )
        assert res.status_code == 201, (user.role, res.data)

    patient = _patient(cedula="00100009999")
    res = auth_client(doctor_user).post(
        "/api/encounters/", _payload(patient, doctor), format="json"
    )
    assert res.status_code == 201, res.data


def test_it_cannot_create_encounter(auth_client, it_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    res = auth_client(it_user).post(
        "/api/encounters/", _payload(patient, doctor), format="json"
    )
    assert res.status_code == 403, res.data


# ---------------------------------------------------------------------------
# Doctor object-level scoping: a doctor may only manage encounters they're
# assigned to (at least one service line), and only sees their own in list
# results.
# ---------------------------------------------------------------------------


def test_doctor_can_only_create_for_self(auth_client, doctor_user, make_user):
    from apps.accounts.models import User

    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _doctor(other_user)
    patient = _patient()
    res = auth_client(doctor_user).post(
        "/api/encounters/", _payload(patient, other_doctor), format="json"
    )
    assert res.status_code == 400, res.data


def test_doctor_only_sees_own_encounters(auth_client, doctor_user, make_user, admin_user):
    """Centerless encounters (no center set) stay self-only -- there's no
    shared center to widen visibility through, so this is unaffected by the
    center-shared scoping added below."""
    from apps.accounts.models import User

    own_doctor = _doctor(doctor_user)
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _doctor(other_user)
    _encounter(_patient(cedula="00100000011"), admin_user, doctor=own_doctor)
    _encounter(_patient(cedula="00100000022"), admin_user, doctor=other_doctor)
    res = auth_client(doctor_user).get("/api/encounters/")
    assert res.data["count"] == 1


def test_doctor_sees_colleagues_encounter_at_shared_center(
    auth_client, doctor_user, make_user, admin_user
):
    """A doctor bound to a center sees another doctor's encounter at that
    same center (matching Patients/Records center-shared scoping), not just
    encounters they personally created."""
    from apps.accounts.models import User
    from apps.centers.models import DoctorCenterBinding

    center = _center()
    own_doctor = _doctor(doctor_user)
    DoctorCenterBinding.objects.create(
        doctor=own_doctor, center=center, approved=True, approved_by=admin_user
    )
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _doctor(other_user)
    _encounter(_patient(cedula="00100000033"), admin_user, doctor=other_doctor, center=center)
    res = auth_client(doctor_user).get("/api/encounters/")
    assert res.data["count"] == 1


def test_doctor_without_binding_does_not_see_other_centers_encounter(
    auth_client, doctor_user, make_user, admin_user
):
    """A doctor with no approved binding to a center still sees nothing
    there, even for another doctor's encounter -- only their own rows."""
    from apps.accounts.models import User

    _doctor(doctor_user)
    center = _center()
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _doctor(other_user)
    _encounter(_patient(cedula="00100000044"), admin_user, doctor=other_doctor, center=center)
    res = auth_client(doctor_user).get("/api/encounters/")
    assert res.data["count"] == 0


def test_doctor_sees_encounter_via_any_service_line(auth_client, doctor_user, make_user, admin_user):
    """A doctor assigned to only the *second* service line on a multi-line
    encounter still sees/owns it -- ownership isn't limited to the first
    line, and the scoped queryset doesn't duplicate the row per line."""
    from apps.accounts.models import User

    own_doctor = _doctor(doctor_user)
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _doctor(other_user)
    patient = _patient()
    service_type = _service_type()
    encounter = Encounter.objects.create(
        service_type=service_type, patient=patient, created_by=admin_user
    )
    encounter.services.create(service=_service(service_type=service_type), doctor=other_doctor)
    encounter.services.create(service=_service(service_type=service_type), doctor=own_doctor)

    res = auth_client(doctor_user).get("/api/encounters/")
    assert res.data["count"] == 1, res.data


# ---------------------------------------------------------------------------
# Admit lifecycle: every non-cancelled service line needs a room,
# encounter_number assigned on admit. A primary diagnosis is no longer
# required to admit (diagnosis capture was removed from the admission flow
# entirely).
# ---------------------------------------------------------------------------


def test_admit_requires_room(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = _encounter(patient, admin_user, doctor=doctor)
    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    assert res.status_code == 400, res.data


def test_admit_does_not_require_a_diagnosis(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    center = _center()
    room = _room(center=center)

    patient1 = _patient(cedula="00100000031")
    encounter1 = _encounter(patient1, admin_user, doctor=doctor, room=room)
    res = auth_client(admin_user).post(f"/api/encounters/{encounter1.id}/admit/")
    assert res.status_code == 200, res.data
    assert res.data["status"] == "ACTIVE"
    assert res.data["encounter_number"]

    patient2 = _patient(cedula="00100000032")
    encounter2 = _encounter(
        patient2, admin_user, doctor=doctor, room=room, service_type=_service_type(name="Vacunación")
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter2.id}/admit/")
    assert res.status_code == 200, res.data


def test_same_day_active_conflict_requires_override(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    room = _room()
    patient = _patient()
    service_type = _service_type(name="Chequeo rápido")

    first = _encounter(patient, admin_user, doctor=doctor, room=room, service_type=service_type)
    auth_client(admin_user).post(f"/api/encounters/{first.id}/admit/")

    second = _encounter(patient, admin_user, doctor=doctor, room=room, service_type=service_type)
    res = auth_client(admin_user).post(f"/api/encounters/{second.id}/admit/")
    assert res.status_code == 400, res.data

    res = auth_client(admin_user).post(
        f"/api/encounters/{second.id}/admit/", {"override_conflict": True}, format="json"
    )
    assert res.status_code == 200, res.data


def test_cancel_and_complete_lifecycle(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    room = _room()
    patient = _patient()
    encounter = _encounter(patient, admin_user, doctor=doctor, room=room)
    auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")

    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/complete/")
    assert res.status_code == 200, res.data
    assert res.data["status"] == "COMPLETED"

    # Can't complete twice.
    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/complete/")
    assert res.status_code == 400, res.data


def test_cancel_draft_encounter(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = _encounter(patient, admin_user, doctor=doctor)
    res = auth_client(admin_user).post(
        f"/api/encounters/{encounter.id}/cancel/", {"reason": "No show"}, format="json"
    )
    assert res.status_code == 200, res.data
    assert res.data["status"] == "CANCELLED"
    assert res.data["cancel_reason"] == "No show"


def test_cannot_edit_completed_encounter(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    room = _room()
    patient = _patient()
    encounter = _encounter(patient, admin_user, doctor=doctor, room=room)
    auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    auth_client(admin_user).post(f"/api/encounters/{encounter.id}/complete/")

    res = auth_client(doctor_user).patch(
        f"/api/encounters/{encounter.id}/", {"chief_complaint": "Edited"}, format="json"
    )
    assert res.status_code == 403, res.data


# ---------------------------------------------------------------------------
# Nested diagnoses/services writable payload.
# ---------------------------------------------------------------------------


def test_create_with_nested_diagnoses_and_services(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    service = _service()
    payload = _payload(
        patient, doctor,
        service_type_id=service.type_id,
        diagnoses=[{"description": "Migraine", "is_primary": True}],
        services=[{"service": service.id, "quantity": 2}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    assert len(res.data["diagnoses"]) == 1
    assert res.data["diagnoses"][0]["description"] == "Migraine"
    assert len(res.data["services"]) == 1
    assert res.data["services"][0]["quantity"] == 2
    assert res.data["services"][0]["service_name"] == "CONSULTA"


# ---------------------------------------------------------------------------
# Per-service doctor/room + ARS coverage: doctor/room/authorization_number
# all live on EncounterService (not Encounter); doctor ownership and the
# requires_doctor rule are enforced per line; authorization_number only
# accepts positive integers and is silently cleared when ars_covered is
# false.
# ---------------------------------------------------------------------------


def test_service_line_carries_its_own_doctor_and_room(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    room = _room()
    patient = _patient()
    service = _service()
    payload = _payload(
        patient, doctor, room,
        service_type_id=service.type_id,
        services=[{"service": service.id, "quantity": 1, "doctor": doctor.id, "room": room.id}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    line = res.data["services"][0]
    assert line["doctor"] == doctor.id
    assert line["room"] == room.id
    assert line["room_name"] == room.name


def test_doctor_can_only_assign_self_on_a_service_line(auth_client, doctor_user, make_user):
    from apps.accounts.models import User

    other_user = make_user("doctor3", User.Role.DOCTOR)
    other_doctor = _doctor(other_user)
    patient = _patient()
    service = _service()
    payload = _payload(
        patient,
        service_type_id=service.type_id,
        services=[{"service": service.id, "quantity": 1, "doctor": other_doctor.id}],
    )
    res = auth_client(doctor_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "services" in res.data


def test_multi_line_encounter_can_have_different_doctors_and_rooms(
    auth_client, admin_user, doctor_user, make_user
):
    """Regression for the reported bug: picking a doctor on one line must
    not purge or overwrite another line's independently-chosen service."""
    from apps.accounts.models import User

    doctor_a = _doctor(doctor_user)
    doctor_b = _doctor(make_user("doctor4", User.Role.DOCTOR))
    center = _center(code="MULTI")
    room_a, room_b = _room(center=center, code="RA"), _room(center=center, code="RB")
    patient = _patient()
    service_a, service_b = _service(simon="200001", name="Consulta A"), _service(simon="200002", name="Consulta B")
    payload = _payload(
        patient,
        service_type_id=service_a.type_id,
        services=[
            {"service": service_a.id, "quantity": 1, "doctor": doctor_a.id, "room": room_a.id},
            {"service": service_b.id, "quantity": 1, "doctor": doctor_b.id, "room": room_b.id},
        ],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    lines = {line["service"]: line for line in res.data["services"]}
    assert lines[service_a.id]["doctor"] == doctor_a.id
    assert lines[service_a.id]["room"] == room_a.id
    assert lines[service_b.id]["doctor"] == doctor_b.id
    assert lines[service_b.id]["room"] == room_b.id


def test_service_line_authorization_number_defaults_covered(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    service = _service()
    payload = _payload(
        patient, doctor,
        service_type_id=service.type_id,
        services=[{"service": service.id, "quantity": 1, "authorization_number": "00012345"}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    line = res.data["services"][0]
    assert line["ars_covered"] is True
    assert line["authorization_number"] == "00012345"


@pytest.mark.parametrize("bad_value", ["0", "000"])
def test_service_line_authorization_number_rejects_non_positive(bad_value, auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    service = _service()
    payload = _payload(
        patient, doctor,
        service_type_id=service.type_id,
        services=[{"service": service.id, "quantity": 1, "authorization_number": bad_value}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 400, res.data


def test_service_line_uncovered_clears_authorization_number(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    service = _service()
    payload = _payload(
        patient, doctor,
        service_type_id=service.type_id,
        services=[{"service": service.id, "quantity": 1, "ars_covered": False, "authorization_number": "999"}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    line = res.data["services"][0]
    assert line["ars_covered"] is False
    assert line["authorization_number"] is None


# ---------------------------------------------------------------------------
# EncounterService.co_pago: resolved once, server-side, at line-creation
# time via apps.services.services.resolve_line_price -- never exposed in the
# API response (no Billing/Cashier module yet), and immutable afterward
# except when the line's own service is swapped. See tests/test_services.py
# for resolve_line_price's own tier-resolution coverage.
# ---------------------------------------------------------------------------


def _ars(name="Test ARS", ars_id="TA"):
    from apps.ars.models import ARS

    return ARS.objects.create(ars_id=ars_id, name=name)


def _program(ars, name="Basico"):
    from apps.ars.models import ARSProgram

    return ARSProgram.objects.create(ars=ars, name=name)


def test_encounter_service_line_snapshots_ars_level_price(auth_client, admin_user, doctor_user):
    from apps.encounters.models import EncounterService
    from apps.services.models import ServicePrice

    doctor = _doctor(doctor_user)
    ars = _ars()
    service = _service(co_pago="500.00", privado="1500.00")
    ServicePrice.objects.create(service=service, ars=ars, co_pago="350.00")
    patient = _patient()
    payload = _payload(
        patient, doctor,
        service_type_id=service.type_id,
        ars=ars.id,
        services=[{"service": service.id, "quantity": 1}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    line = EncounterService.objects.get(pk=res.data["services"][0]["id"])
    assert str(line.co_pago) == "350.00"


def test_encounter_service_line_uncovered_snapshots_privado(auth_client, admin_user, doctor_user):
    from apps.encounters.models import EncounterService

    doctor = _doctor(doctor_user)
    ars = _ars()
    service = _service(co_pago="500.00", privado="1500.00")
    patient = _patient()
    payload = _payload(
        patient, doctor,
        service_type_id=service.type_id,
        ars=ars.id,
        services=[{"service": service.id, "quantity": 1, "ars_covered": False}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    line = EncounterService.objects.get(pk=res.data["services"][0]["id"])
    assert str(line.co_pago) == "1500.00"


def test_encounter_service_line_price_locked_after_ars_change(auth_client, admin_user, doctor_user):
    """Changing the encounter's ARS after a line exists must not retroactively
    reprice it -- the co_pago snapshot is immutable billing history."""
    from apps.encounters.models import EncounterService
    from apps.services.models import ServicePrice

    doctor = _doctor(doctor_user)
    ars_a = _ars(name="Test ARS A", ars_id="TAA")
    ars_b = _ars(name="Test ARS B", ars_id="TAB")
    service = _service(co_pago="500.00", privado="1500.00")
    ServicePrice.objects.create(service=service, ars=ars_a, co_pago="350.00")
    ServicePrice.objects.create(service=service, ars=ars_b, co_pago="900.00")
    patient = _patient()
    payload = _payload(
        patient, doctor,
        service_type_id=service.type_id,
        ars=ars_a.id,
        services=[{"service": service.id, "quantity": 1}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    encounter_id = res.data["id"]
    line_id = res.data["services"][0]["id"]

    res = auth_client(admin_user).patch(
        f"/api/encounters/{encounter_id}/",
        {"ars": ars_b.id, "services": [{"id": line_id, "service": service.id, "quantity": 1}]},
        format="json",
    )
    assert res.status_code == 200, res.data
    line = EncounterService.objects.get(pk=line_id)
    assert str(line.co_pago) == "350.00"


def test_encounter_service_line_price_recomputed_on_service_swap(auth_client, admin_user, doctor_user):
    from apps.encounters.models import EncounterService

    doctor = _doctor(doctor_user)
    ars = _ars()
    service_a = _service(simon="300001", name="A", co_pago="100.00", privado="200.00")
    service_b = _service(simon="300002", name="B", co_pago="700.00", privado="900.00")
    patient = _patient()
    payload = _payload(
        patient, doctor,
        service_type_id=service_a.type_id,
        ars=ars.id,
        services=[{"service": service_a.id, "quantity": 1}],
    )
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    encounter_id = res.data["id"]
    line_id = res.data["services"][0]["id"]
    line = EncounterService.objects.get(pk=line_id)
    assert str(line.co_pago) == "100.00"

    res = auth_client(admin_user).patch(
        f"/api/encounters/{encounter_id}/",
        {"services": [{"id": line_id, "service": service_b.id, "quantity": 1}]},
        format="json",
    )
    assert res.status_code == 200, res.data
    line.refresh_from_db()
    assert str(line.co_pago) == "700.00"


def test_update_replaces_nested_diagnoses(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = _encounter(patient, admin_user, doctor=doctor)
    encounter.diagnoses.create(description="Old", is_primary=True)
    res = auth_client(admin_user).patch(
        f"/api/encounters/{encounter.id}/",
        {"diagnoses": [{"description": "New", "is_primary": True}]},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert encounter.diagnoses.count() == 1
    assert encounter.diagnoses.first().description == "New"


# ---------------------------------------------------------------------------
# At least one service is required to save an encounter at all (even a
# Draft), and each service line's doctor is required only when that line's
# own Service.type.requires_doctor is true.
# ---------------------------------------------------------------------------


def test_create_without_services_rejected(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    payload = _payload(patient, doctor, services=[])
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "services" in res.data


def test_doctor_required_when_service_type_requires_it(auth_client, admin_user):
    patient = _patient()
    service_type = _service_type(name="Emergencia", requires_doctor=True)
    service = _service(service_type=service_type)
    payload = {
        "service_type": service_type.id,
        "patient": patient.id,
        "chief_complaint": "Fever",
        "services": [{"service": service.id, "quantity": 1}],
    }
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "doctor" in res.data["services"][0]


def test_doctor_not_required_when_service_type_does_not_require_it(auth_client, admin_user):
    patient = _patient()
    service_type = _service_type(name="Laboratorio", requires_doctor=False)
    service = _service(service_type=service_type)
    payload = {
        "service_type": service_type.id,
        "patient": patient.id,
        "chief_complaint": "Routine labs",
        "services": [{"service": service.id, "quantity": 1}],
    }
    res = auth_client(admin_user).post("/api/encounters/", payload, format="json")
    assert res.status_code == 201, res.data
    assert res.data["services"][0]["doctor"] is None


# ---------------------------------------------------------------------------
# Masking: chief_complaint/diagnosis text masked for non-clinical roles;
# patient summary PII masked for IT/center_manager.
# ---------------------------------------------------------------------------


def test_chief_complaint_masked_for_receptionist(auth_client, admin_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = _encounter(patient, admin_user, doctor=doctor, chief_complaint="Chest pain")
    res = auth_client(receptionist_user).get(f"/api/encounters/{encounter.id}/")
    assert res.data["chief_complaint"] != "Chest pain"

    res = auth_client(doctor_user).get(f"/api/encounters/{encounter.id}/")
    assert res.data["chief_complaint"] == "Chest pain"


def test_patient_summary_masked_for_it_but_not_center_manager(
    auth_client, admin_user, doctor_user, it_user, center_manager_user
):
    doctor = _doctor(doctor_user)
    patient = _patient(allergies="Penicillin")
    encounter = _encounter(patient, admin_user, doctor=doctor)
    res = auth_client(it_user).get(f"/api/encounters/{encounter.id}/")
    assert res.data["patient_info"]["allergies"] != "Penicillin"

    # CENTER_MANAGER is admin-equivalent app-wide (except Settings edit), so
    # it sees full PII like admin, unlike IT.
    for user in (admin_user, center_manager_user):
        res = auth_client(user).get(f"/api/encounters/{encounter.id}/")
        assert res.data["patient_info"]["allergies"] == "Penicillin", user.role


# ---------------------------------------------------------------------------
# encounter_number format: clinic-wide daily sequence, no center/ENC prefix.
# ---------------------------------------------------------------------------


def test_server_timezone_is_clinic_local_not_utc():
    """generate_encounter_number's YYYYMMDD prefix comes from
    timezone.localdate(), which is only the clinic's actual calendar day if
    TIME_ZONE is the clinic's own zone -- defaulting to UTC (as Django does
    out of the box) silently shifts the admission-number date by several
    hours whenever "now" and UTC-midnight fall on different local days.
    """
    from django.conf import settings

    assert settings.TIME_ZONE == "America/Santo_Domingo"


def test_encounter_number_is_date_and_daily_sequence(auth_client, admin_user, doctor_user):
    from django.utils import timezone

    doctor = _doctor(doctor_user)
    room = _room()
    service_type = _service_type()
    today = timezone.localdate()

    first = _encounter(
        _patient(cedula="00100000041"), admin_user, doctor=doctor, room=room, service_type=service_type
    )
    auth_client(admin_user).post(f"/api/encounters/{first.id}/admit/")
    first.refresh_from_db()
    assert first.encounter_number == f"{today:%Y%m%d}-001"

    second = _encounter(
        _patient(cedula="00100000042"), admin_user, doctor=doctor, room=room, service_type=service_type
    )
    auth_client(admin_user).post(f"/api/encounters/{second.id}/admit/")
    second.refresh_from_db()
    assert second.encounter_number == f"{today:%Y%m%d}-002"


# ---------------------------------------------------------------------------
# Search: patient's own cedula digits find the encounter; doctor code and
# encounter number also match; masked roles get no digit-based patient
# lookup (PII-existence-oracle guard).
# ---------------------------------------------------------------------------


def test_search_by_patient_cedula_digits(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    target = _patient(cedula="00112345678")
    other = _patient(cedula="00199999999")
    _encounter(target, admin_user, doctor=doctor)
    _encounter(other, admin_user, doctor=doctor)

    res = auth_client(admin_user).get("/api/encounters/?search=00112345678")
    assert res.data["count"] == 1
    assert res.data["results"][0]["patient"] == target.id


def test_search_by_doctor_code_and_encounter_number(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = _encounter(patient, admin_user, doctor=doctor, room=_room())
    auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    encounter.refresh_from_db()

    res = auth_client(admin_user).get(f"/api/encounters/?search={doctor.code}")
    assert res.data["count"] == 1

    res = auth_client(admin_user).get(f"/api/encounters/?search={encounter.encounter_number}")
    assert res.data["count"] == 1


def test_masked_role_gets_no_cedula_digit_search(auth_client, it_user, doctor_user, admin_user):
    doctor = _doctor(doctor_user)
    patient = _patient(cedula="00112345678")
    _encounter(patient, admin_user, doctor=doctor)

    res = auth_client(it_user).get("/api/encounters/?search=00112345678")
    assert res.data["count"] == 0
