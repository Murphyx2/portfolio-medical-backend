"""Encounters module: RBAC (read=all staff, write=admin/doctor/receptionist/
nurse/center_manager, IT read-only), doctor object-level scoping (own
encounters only), DRAFT->ACTIVE->COMPLETED/CANCELLED status lifecycle via the
admit/cancel/complete actions, encounter_number assignment on admit,
same-day-active-encounter conflict detection with override, primary-diagnosis
requirement (unless the EncounterType is exempted), and clinical-text/PII
masking.
"""

from apps.centers.models import MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.encounters.models import Encounter, EncounterType
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


def _encounter_type(name="Consulta General", requires_diagnosis=True):
    # get_or_create()'s `defaults` only applies on insert -- explicitly sync
    # requires_diagnosis on every call so a test overriding it for an
    # already-seeded name (e.g. "Consulta General" from the 0002 seed
    # migration) actually takes effect instead of silently keeping the
    # seeded value.
    encounter_type, _ = EncounterType.objects.get_or_create(name=name)
    if encounter_type.requires_diagnosis != requires_diagnosis:
        encounter_type.requires_diagnosis = requires_diagnosis
        encounter_type.save()
    return encounter_type


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


def _service():
    service_type = ServiceType.objects.create(name="Consult")
    return Service.objects.create(
        simon="123456", name="Consulta", type=service_type, co_pago="0", privado="0"
    )


def _payload(patient, doctor, **overrides):
    data = {
        "encounter_type": overrides.pop("encounter_type_id", None) or _encounter_type().id,
        "patient": patient.id,
        "doctor": doctor.id,
        "chief_complaint": "Fever",
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
        encounter_type=_encounter_type(), patient=patient, doctor=doctor, created_by=admin_user
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
    from apps.accounts.models import User

    own_doctor = _doctor(doctor_user)
    other_user = make_user("doctor2", User.Role.DOCTOR)
    other_doctor = _doctor(other_user)
    Encounter.objects.create(
        encounter_type=_encounter_type(), patient=_patient(cedula="00100000011"),
        doctor=own_doctor, created_by=admin_user,
    )
    Encounter.objects.create(
        encounter_type=_encounter_type(), patient=_patient(cedula="00100000022"),
        doctor=other_doctor, created_by=admin_user,
    )
    res = auth_client(doctor_user).get("/api/encounters/")
    assert res.data["count"] == 1


# ---------------------------------------------------------------------------
# Admit lifecycle: room required, primary diagnosis required unless the
# encounter type is exempted, encounter_number assigned on admit.
# ---------------------------------------------------------------------------


def test_admit_requires_room(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = Encounter.objects.create(
        encounter_type=_encounter_type(), patient=patient, doctor=doctor, created_by=admin_user
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
        encounter_type=_encounter_type(requires_diagnosis=True),
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
        encounter_type=_encounter_type(name="Vacunación", requires_diagnosis=False),
        patient=patient2, doctor=doctor, room=room, created_by=admin_user,
    )
    res = auth_client(admin_user).post(f"/api/encounters/{encounter2.id}/admit/")
    assert res.status_code == 200, res.data


def test_same_day_active_conflict_requires_override(auth_client, admin_user, doctor_user):
    doctor = _doctor(doctor_user)
    room = _room()
    patient = _patient()
    encounter_type = _encounter_type(name="Chequeo rápido", requires_diagnosis=False)

    first = Encounter.objects.create(
        encounter_type=encounter_type, patient=patient, doctor=doctor, room=room,
        created_by=admin_user,
    )
    auth_client(admin_user).post(f"/api/encounters/{first.id}/admit/")

    second = Encounter.objects.create(
        encounter_type=encounter_type, patient=patient, doctor=doctor, room=room,
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
        encounter_type=_encounter_type(requires_diagnosis=False), patient=patient,
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
        encounter_type=_encounter_type(), patient=patient, doctor=doctor, created_by=admin_user
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
        encounter_type=_encounter_type(requires_diagnosis=False), patient=patient,
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
        encounter_type=_encounter_type(), patient=patient, doctor=doctor, created_by=admin_user
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
# Masking: chief_complaint/diagnosis text masked for non-clinical roles;
# patient summary PII masked for IT/center_manager.
# ---------------------------------------------------------------------------


def test_chief_complaint_masked_for_receptionist(auth_client, admin_user, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    encounter = Encounter.objects.create(
        encounter_type=_encounter_type(), patient=patient, doctor=doctor,
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
        encounter_type=_encounter_type(), patient=patient, doctor=doctor, created_by=admin_user
    )
    for user in (it_user, center_manager_user):
        res = auth_client(user).get(f"/api/encounters/{encounter.id}/")
        assert res.data["patient_info"]["allergies"] != "Penicillin", user.role

    res = auth_client(admin_user).get(f"/api/encounters/{encounter.id}/")
    assert res.data["patient_info"]["allergies"] == "Penicillin"
