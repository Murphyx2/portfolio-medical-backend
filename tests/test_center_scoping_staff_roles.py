"""HTTP-level regression tests for extending center scoping (previously
DOCTOR-only, see apps/core/services/scoping.py) to non-doctor staff roles:
RECEPTIONIST, IT, NURSE, CENTER_MANAGER. ADMIN stays globally unscoped by
design. Function-level coverage of the resolver itself lives in
test_core_invariants.py; these tests exercise the actual viewsets."""

from apps.centers.models import MedicalCenter
from apps.patients.models import Patient
from apps.records.models import MedicalRecord


def _center(**overrides):
    data = {"name": "Center", "code": "SC", "address": "1 St", "phone": "8095551111"}
    data.update(overrides)
    return MedicalCenter.objects.create(**data)


def _patient_payload(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "birth_date": "1990-05-12",
        "gender": "FEMALE",
        "phone": "8095550100",
        "cedula": "00122220001",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Medical records
# ---------------------------------------------------------------------------


def test_nurse_with_assigned_center_only_sees_that_centers_records(
    auth_client, receptionist_user, nurse_user
):
    own_center = _center(code="MR-OWN")
    other_center = _center(code="MR-OTHER")
    nurse_user.center = own_center
    nurse_user.save(update_fields=["center"])

    creator = auth_client(receptionist_user)
    own_patient = creator.post(
        "/api/patients/", _patient_payload(cedula="00122220002", center=own_center.id), format="json"
    ).data
    other_patient = creator.post(
        "/api/patients/", _patient_payload(cedula="00122220003", center=other_center.id), format="json"
    ).data

    record_ids = {
        r["id"]
        for r in auth_client(nurse_user).get("/api/medical-records/?page_size=100").data["results"]
    }
    own_record = MedicalRecord.objects.get(patient_id=own_patient["id"])
    other_record = MedicalRecord.objects.get(patient_id=other_patient["id"])
    assert own_record.id in record_ids
    assert other_record.id not in record_ids


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def test_center_scoped_receptionist_sees_own_center_staff_and_unassigned(
    auth_client, admin_user, make_user
):
    """The viewer is IT (not RECEPTIONIST) because UserViewSet itself is
    gated to Admin/IT/CenterManager -- a plain receptionist can't call this
    endpoint at all, regardless of center scoping."""
    from apps.accounts.models import User

    center_a = _center(code="USR-A")
    center_b = _center(code="USR-B")
    viewer = make_user("it-a", User.Role.IT, center=center_a)
    same_center_colleague = make_user("front-desk-a2", User.Role.RECEPTIONIST, center=center_a)
    other_center_staff = make_user("front-desk-b", User.Role.RECEPTIONIST, center=center_b)
    unassigned_staff = make_user("it-unassigned", User.Role.IT)

    visible_ids = {
        u["id"] for u in auth_client(viewer).get("/api/auth/users/?page_size=100").data["results"]
    }
    assert same_center_colleague.id in visible_ids
    assert unassigned_staff.id in visible_ids  # unassigned = still visible (rollout safety)
    assert other_center_staff.id not in visible_ids


def test_admin_sees_every_staff_member_regardless_of_center(auth_client, admin_user, make_user):
    from apps.accounts.models import User

    center = _center(code="USR-ADMIN")
    staff = make_user("front-desk-c", User.Role.RECEPTIONIST, center=center)

    visible_ids = {
        u["id"] for u in auth_client(admin_user).get("/api/auth/users/?page_size=100").data["results"]
    }
    assert staff.id in visible_ids
