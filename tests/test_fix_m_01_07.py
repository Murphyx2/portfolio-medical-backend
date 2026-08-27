"""Security fixes M-02 / M-03 / M-05 / M-07.

- M-02: a nurse may create/update records but may only update ones they
  created (the data model has no nurse-to-center relationship yet); doctors
  keep center scoping; admins are unrestricted. DELETE itself was later
  narrowed further by the Expedientes Médicos spec to Admin-only for every
  role, superseding "own records" for that one verb.
- M-03: doctor contact PII (license_number / contact_phone / contact_email /
  bio) is masked for staff who are not admin/IT or the doctor themself.
- M-05: API and media responses carry ``Cache-Control: private, no-store``.
- M-07: changes made through Django admin are written to the app AuditLog.
"""

from types import SimpleNamespace

from apps.centers.models import MedicalCenter
from apps.core.admin import AuditModelAdmin
from apps.core.models import AuditLog
from apps.core.permissions import CanManageRecords
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient
from apps.records.models import MedicalRecord


def _patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "birth_date": "1990-05-12",
        "phone": "8095550100",
        "cedula": "00112345678",
        "nss": "98765432109",
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _center(code="C1"):
    return MedicalCenter.objects.create(
        name=f"Center {code}", code=code, address="A", phone="1"
    )


def _doctor_profile(user):
    return DoctorProfile.objects.create(
        user=user,
        license_number="LIC-123",
        contact_phone="8095550000",
        contact_email="doc@example.com",
        bio="Experienced cardiologist.",
    )


def _record(patient, user, center=None):
    return MedicalRecord.objects.create(patient=patient, created_by=user, center=center)


# ---------------------------------------------------------------------------
# M-02: nurse write-scoping (own records only)
#
# MedicalRecord carries no clinical content field of its own anymore (that
# moved to RecordEntry as part of the Expedientes Médicos refactor) -- these
# tests now PATCH `center` (still a plain writable field on the anchor row)
# to exercise the same edit-scoping rule that used to PATCH `title`.
# ---------------------------------------------------------------------------


def test_nurse_cannot_edit_record_created_by_another(auth_client, nurse_user, make_user):
    other = make_user("doctor", "DOCTOR")
    patient = _patient()
    record = _record(patient, other)
    center = _center()
    res = auth_client(nurse_user).patch(
        f"/api/medical-records/{record.id}/", {"center": center.id}, format="json"
    )
    assert res.status_code == 403, res.data
    record.refresh_from_db()
    assert record.center_id is None


def test_nurse_cannot_delete_record_created_by_another(auth_client, nurse_user, make_user):
    other = make_user("doctor", "DOCTOR")
    patient = _patient()
    record = _record(patient, other)
    res = auth_client(nurse_user).delete(f"/api/medical-records/{record.id}/")
    assert res.status_code == 403, res.data
    assert MedicalRecord.objects.filter(pk=record.id).exists()


def test_nurse_can_edit_own_record(auth_client, nurse_user):
    patient = _patient()
    record = _record(patient, nurse_user)
    center = _center()
    res = auth_client(nurse_user).patch(
        f"/api/medical-records/{record.id}/", {"center": center.id}, format="json"
    )
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert record.center_id == center.id


def test_nurse_cannot_delete_own_record(auth_client, nurse_user):
    # Narrowed by the Expedientes Médicos spec (section 3): soft-deleting an
    # expediente is Admin-only now, even for a nurse deleting their own
    # record -- delete_permission_classes=[IsAdmin] on MedicalRecordViewSet
    # supersedes the M-02 "own records" write scope for DELETE specifically.
    patient = _patient()
    record = _record(patient, nurse_user)
    res = auth_client(nurse_user).delete(f"/api/medical-records/{record.id}/")
    assert res.status_code == 403
    assert MedicalRecord.objects.filter(pk=record.id).exists()


def test_admin_can_delete_any_record(auth_client, admin_user, make_user):
    other = make_user("doctor", "DOCTOR")
    patient = _patient()
    record = _record(patient, other)
    res = auth_client(admin_user).delete(f"/api/medical-records/{record.id}/")
    assert res.status_code == 204
    # Soft-delete: the row still exists, just deactivated -- not gone.
    assert not MedicalRecord.objects.filter(pk=record.id).exists()
    assert MedicalRecord.all_objects.get(pk=record.id).active is False


def test_nurse_can_create_record(auth_client, nurse_user):
    patient = _patient()
    res = auth_client(nurse_user).post(
        "/api/medical-records/", {"patient": patient.id}, format="json"
    )
    assert res.status_code == 201, res.data


def test_admin_can_edit_any_record(auth_client, admin_user, make_user):
    other = make_user("doctor", "DOCTOR")
    patient = _patient()
    record = _record(patient, other)
    center = _center()
    res = auth_client(admin_user).patch(
        f"/api/medical-records/{record.id}/", {"center": center.id}, format="json"
    )
    assert res.status_code == 200, res.data


def test_can_manage_records_resolves_owner_for_all_models(nurse_user):
    # The object-level rule must recognize the owner field of every model the
    # permission guards: MedicalRecord.created_by, RecordImage.uploaded_by,
    # and (falling back to the parent record's creator) RecordPersonalCondition/
    # RecordFamilyCondition, which have no owner field of their own.
    perm = CanManageRecords()

    class FakeRequest:
        method = "DELETE"

    req = FakeRequest()
    req.user = nurse_user
    theirs = SimpleNamespace(created_by_id=999, uploaded_by_id=None, doctor_id=None, record=None)
    assert perm.has_object_permission(req, None, theirs) is False
    own_created = SimpleNamespace(created_by_id=nurse_user.id, uploaded_by_id=None, doctor_id=None, record=None)
    assert perm.has_object_permission(req, None, own_created) is True
    own_uploaded = SimpleNamespace(created_by_id=None, uploaded_by_id=nurse_user.id, doctor_id=None, record=None)
    assert perm.has_object_permission(req, None, own_uploaded) is True
    own_logged = SimpleNamespace(created_by_id=None, uploaded_by_id=None, doctor_id=nurse_user.id, record=None)
    assert perm.has_object_permission(req, None, own_logged) is True
    own_condition = SimpleNamespace(
        created_by_id=None, uploaded_by_id=None, doctor_id=None,
        record=SimpleNamespace(created_by_id=nurse_user.id),
    )
    assert perm.has_object_permission(req, None, own_condition) is True
    foreign_condition = SimpleNamespace(
        created_by_id=None, uploaded_by_id=None, doctor_id=None,
        record=SimpleNamespace(created_by_id=999),
    )
    assert perm.has_object_permission(req, None, foreign_condition) is False


# ---------------------------------------------------------------------------
# M-03: doctor contact PII masking
# ---------------------------------------------------------------------------


def _doctor_detail(auth_client, user, profile):
    res = auth_client(user).get(f"/api/doctors/profiles/{profile.id}/")
    assert res.status_code == 200, res.data
    return res.data


def test_receptionist_sees_unmasked_contact_but_masked_license(auth_client, receptionist_user, doctor_user):
    prof = _doctor_profile(doctor_user)
    data = _doctor_detail(auth_client, receptionist_user, prof)
    assert data["full_name"]
    assert data["contact_phone"] == "8095550000"
    assert data["contact_email"] == "doc@example.com"
    assert data["license_number"] != "LIC-123" and "••••" in data["license_number"]
    assert data["bio"] is None


def test_nurse_sees_masked_doctor_contact(auth_client, nurse_user, doctor_user):
    prof = _doctor_profile(doctor_user)
    data = _doctor_detail(auth_client, nurse_user, prof)
    assert data["contact_phone"] != "8095550000"
    assert data["contact_email"] != "doc@example.com" and "••••" in data["contact_email"]


def test_admin_sees_full_doctor_contact(auth_client, admin_user, doctor_user):
    prof = _doctor_profile(doctor_user)
    data = _doctor_detail(auth_client, admin_user, prof)
    assert data["license_number"] == "LIC-123"
    assert data["contact_phone"] == "8095550000"
    assert data["contact_email"] == "doc@example.com"
    assert data["bio"] == "Experienced cardiologist."


def test_it_sees_full_doctor_contact(auth_client, it_user, doctor_user):
    prof = _doctor_profile(doctor_user)
    data = _doctor_detail(auth_client, it_user, prof)
    assert data["contact_phone"] == "8095550000"
    assert data["contact_email"] == "doc@example.com"


def test_doctor_sees_own_full_contact(auth_client, doctor_user):
    prof = _doctor_profile(doctor_user)
    data = _doctor_detail(auth_client, doctor_user, prof)
    assert data["contact_phone"] == "8095550000"
    assert data["contact_email"] == "doc@example.com"


# ---------------------------------------------------------------------------
# M-05: no-store on API/media responses
# ---------------------------------------------------------------------------


def test_api_response_has_no_store_header(api_client):
    res = api_client.get("/api/health/")
    assert res.status_code == 200
    assert res["Cache-Control"] == "private, no-store, max-age=0"
    assert res["Pragma"] == "no-cache"


def test_missing_api_path_still_no_store(api_client):
    res = api_client.get("/api/nope/")
    assert res.status_code == 404
    assert res["Cache-Control"] == "private, no-store, max-age=0"


def test_non_api_path_not_no_store(api_client):
    res = api_client.get("/favicon.ico/")
    assert res.status_code == 404
    assert "Cache-Control" not in res


# ---------------------------------------------------------------------------
# M-07: Django admin writes go to the app AuditLog
# ---------------------------------------------------------------------------


def test_admin_add_patient_writes_audit_log(client, admin_user):
    client.force_login(admin_user)
    res = client.post(
        "/admin/patients/patient/add/",
        {
            "first_name": "Ana",
            "last_name": "Admin",
            "gender": "FEMALE",
            "birth_date": "1990-05-12",
            "cedula": "00100000001",
        },
    )
    assert res.status_code == 302, res.status_code
    assert AuditLog.objects.filter(
        action="CREATE", target_type="Patient", user=admin_user
    ).exists()


def test_admin_change_patient_writes_audit_log(client, admin_user):
    patient = _patient()
    client.force_login(admin_user)
    res = client.post(
        f"/admin/patients/patient/{patient.id}/change/",
        {
            "first_name": "Jane",
            "last_name": "Renamed",
            "gender": "FEMALE",
            "birth_date": patient.birth_date,
            "phone": patient.phone,
            "address": patient.address,
            "email": patient.email,
            "cedula": patient.cedula,
            "nss": patient.nss,
            "search_name": patient.search_name,
            "cedula_last4": patient.cedula_last4,
            "nss_last4": patient.nss_last4,
        },
    )
    assert res.status_code == 302, res.status_code
    assert AuditLog.objects.filter(
        action="UPDATE", target_type="Patient", user=admin_user, target_id=patient.id
    ).exists()


def test_admin_delete_patient_writes_audit_log(client, admin_user):
    patient = _patient()
    client.force_login(admin_user)
    res = client.post(f"/admin/patients/patient/{patient.id}/delete/", {"post": "yes"})
    assert res.status_code == 302, res.status_code
    assert AuditLog.objects.filter(
        action="DELETE", target_type="Patient", user=admin_user, target_id=patient.id
    ).exists()
    assert not Patient.objects.filter(pk=patient.id).exists()


def test_admin_registrations_inherit_audit_base():
    # Every ModelAdmin must go through AuditModelAdmin so admin edits cannot
    # bypass the app AuditLog.
    from apps.patients.admin import PatientAdmin

    assert issubclass(PatientAdmin, AuditModelAdmin)
