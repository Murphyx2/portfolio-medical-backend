"""Encounters module: RBAC (read=all staff, write=admin/doctor/receptionist/
nurse/center_manager, IT read-only), doctor object-level scoping (own
encounters only), DRAFT->ACTIVE->COMPLETED/CANCELLED status lifecycle via the
admit/cancel/complete actions, encounter_number assignment on admit,
same-day-active-encounter conflict detection with override, primary-diagnosis
requirement (unless the ServiceType is exempted), the at-least-one-service
requirement, the ServiceType.requires_doctor conditional doctor requirement,
and clinical-text/PII masking.

Encounter.service_type is the same `apps.services.ServiceType` catalog the
Services page manages (merged from the former, now-deleted EncounterType).
"""

from apps.centers.models import MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.encounters.models import Encounter
from apps.patients.models import Patient
from apps.rooms.models import Room, RoomType
from apps.services.models import Service, ServiceType


def _center(code="C1"):
    return MedicalCenter.objects.create(name=f"Center {code}", code=code, address="A", phone="1")


def _room(center=None, code="R1"):
    room_type = RoomType.objects.get_or_create(name="Consulta")[0]
    return Room.objects.create(
        code=code, name="Room", room_type=room_type, center=center or _center()
    )


def _service_type(name="Consulta General", requires_doctor=False, requires_diagnosis=True):
    # get_or_create()'s `defaults` only applies on insert -- explicitly sync
    # both flags on every call so a test overriding one for an already-seeded
    # name actually takes effect instead of silently keeping the prior value.
    service_type, _ = ServiceType.objects.get_or_create(name=name)
    changed = False
    if service_type.requires_doctor != requires_doctor:
        service_type.requires_doctor = requires_doctor
        changed = True
    if service_type.requires_diagnosis != requires_diagnosis:
        service_type.requires_diagnosis = requires_diagnosis
        changed = True
    if changed:
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
        "specialty": "Cardiology",
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


def _payload(patient, doctor, **overrides):
    service_type_id = overrides.pop("service_type_id", None)
    service_type = (
        ServiceType.objects.get(pk=service_type_id) if service_type_id else _service_type()
    )
    services = overrides.pop("services", None)
    if services is None:
        services = [{"service": _service(service_type=service_type).id, "quantity": 1}]
    data = {
        "service_type": service_type.id,
        "patient": patient.id,
        "doctor": doctor.id if doctor else None,
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
    Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, created_by=admin_user
    )
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
# Doctor object-level scoping: a doctor may only manage their own encounters,
# and only sees their own in list results.
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
    Encounter.objects.create(
        service_type=_service_type(), patient=_patient(cedula="00100000011"),
        doctor=own_doctor, created_by=admin_user,
    )
    Encounter.objects.create(
        service_type=_service_type(), patient=_patient(cedula="00100000022"),
        doctor=other_doctor, created_by=admin_user,
    )
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
    Encounter.objects.create(
        service_type=_service_type(), patient=_patient(cedula="00100000033"),
        doctor=other_doctor, center=center, created_by=admin_user,
    )
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
    Encounter.objects.create(
        service_type=_service_type(), patient=_patient(cedula="00100000044"),
        doctor=other_doctor, center=center, created_by=admin_user,
    )
    res = auth_client(doctor_user).get("/api/encounters/")
    assert res.data["count"] == 0


# ---------------------------------------------------------------------------
# Admit lifecycle: room required, primary diagnosis required unless the
# service type is exempted, encounter_number assigned on admit.
# ---------------------------------------------------------------------------


def test_admit_requires_room(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, created_by=admin_user
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    assert res.status_code == 400, res.data


def test_admit_requires_primary_diagnosis_unless_exempted(
    auth_client, admin_user, doctor_user
):
    doctor = _doctor(doctor_user)
    center = _center()
    room = _room(center=center)

    # Non-exempted type: blocked without a primary diagnosis.
    patient1 = _patient(cedula="00100000031")
    encounter1 = Encounter.objects.create(
        service_type=_service_type(requires_diagnosis=True),
        patient=patient1, doctor=doctor, room=room, created_by=admin_user,
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter1.id}/admit/")
    assert res.status_code == 400, res.data

    encounter1.diagnoses.create(description="Flu", is_primary=True)
    res = auth_client(admin_user).post(f"/api/encounters/{encounter1.id}/admit/")
    assert res.status_code == 200, res.data
    assert res.data["status"] == "ACTIVE"
    assert res.data["encounter_number"]

    # Exempted type: admits with no diagnosis at all.
    patient2 = _patient(cedula="00100000032")
    encounter2 = Encounter.objects.create(
        service_type=_service_type(name="Vacunación", requires_diagnosis=False),
        patient=patient2, doctor=doctor, room=room, created_by=admin_user,
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter2.id}/admit/")
    assert res.status_code == 200, res.data


def test_same_day_active_conflict_requires_override(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    room = _room()
    patient = _patient()
    service_type = _service_type(name="Chequeo rápido", requires_diagnosis=False)

    first = Encounter.objects.create(
        service_type=service_type, patient=patient, doctor=doctor, room=room,
        created_by=admin_user,
    )
    auth_client(admin_user).post(f"/api/encounters/{first.id}/admit/")

    second = Encounter.objects.create(
        service_type=service_type, patient=patient, doctor=doctor, room=room,
        created_by=admin_user,
    )
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
    encounter = Encounter.objects.create(
        service_type=_service_type(requires_diagnosis=False), patient=patient,
        doctor=doctor, room=room, created_by=admin_user,
    )
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
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, created_by=admin_user
    )
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
    encounter = Encounter.objects.create(
        service_type=_service_type(requires_diagnosis=False), patient=patient,
        doctor=doctor, room=room, created_by=admin_user,
    )
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
    assert res.data["services"][0]["service_name"] == "Consulta"


def test_update_replaces_nested_diagnoses(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, created_by=admin_user
    )
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
# Draft), and the doctor field is required only when the selected
# ServiceType.requires_doctor is true.
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
    assert "doctor" in res.data


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
    assert res.data["doctor"] is None


# ---------------------------------------------------------------------------
# Masking: chief_complaint/diagnosis text masked for non-clinical roles;
# patient summary PII masked for IT/center_manager.
# ---------------------------------------------------------------------------


def test_chief_complaint_masked_for_receptionist(auth_client, admin_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor,
        chief_complaint="Chest pain", created_by=admin_user,
    )
    res = auth_client(receptionist_user).get(f"/api/encounters/{encounter.id}/")
    assert res.data["chief_complaint"] != "Chest pain"

    res = auth_client(doctor_user).get(f"/api/encounters/{encounter.id}/")
    assert res.data["chief_complaint"] == "Chest pain"


def test_patient_summary_masked_for_it_and_center_manager(
    auth_client, admin_user, doctor_user, it_user, center_manager_user
):
    doctor = _doctor(doctor_user)
    patient = _patient(allergies="Penicillin")
    encounter = Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, created_by=admin_user
    )
    for user in (it_user, center_manager_user):
        res = auth_client(user).get(f"/api/encounters/{encounter.id}/")
        assert res.data["patient_info"]["allergies"] != "Penicillin", user.role

    res = auth_client(admin_user).get(f"/api/encounters/{encounter.id}/")
    assert res.data["patient_info"]["allergies"] == "Penicillin"


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
    service_type = _service_type(requires_diagnosis=False)
    today = timezone.localdate()

    first = Encounter.objects.create(
        service_type=service_type, patient=_patient(cedula="00100000041"),
        doctor=doctor, room=room, created_by=admin_user,
    )
    auth_client(admin_user).post(f"/api/encounters/{first.id}/admit/")
    first.refresh_from_db()
    assert first.encounter_number == f"{today:%Y%m%d}-001"

    second = Encounter.objects.create(
        service_type=service_type, patient=_patient(cedula="00100000042"),
        doctor=doctor, room=room, created_by=admin_user,
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
    Encounter.objects.create(
        service_type=_service_type(), patient=target, doctor=doctor, created_by=admin_user
    )
    Encounter.objects.create(
        service_type=_service_type(), patient=other, doctor=doctor, created_by=admin_user
    )

    res = auth_client(admin_user).get("/api/encounters/?search=00112345678")
    assert res.data["count"] == 1
    assert res.data["results"][0]["patient"] == target.id


def test_search_by_doctor_code_and_encounter_number(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = Encounter.objects.create(
        service_type=_service_type(requires_diagnosis=False), patient=patient,
        doctor=doctor, room=_room(), created_by=admin_user,
    )
    auth_client(admin_user).post(f"/api/encounters/{encounter.id}/admit/")
    encounter.refresh_from_db()

    res = auth_client(admin_user).get(f"/api/encounters/?search={doctor.code}")
    assert res.data["count"] == 1

    res = auth_client(admin_user).get(f"/api/encounters/?search={encounter.encounter_number}")
    assert res.data["count"] == 1


def test_masked_role_gets_no_cedula_digit_search(auth_client, it_user, doctor_user, admin_user):
    doctor = _doctor(doctor_user)
    patient = _patient(cedula="00112345678")
    Encounter.objects.create(
        service_type=_service_type(), patient=patient, doctor=doctor, created_by=admin_user
    )

    res = auth_client(it_user).get("/api/encounters/?search=00112345678")
    assert res.data["count"] == 0
