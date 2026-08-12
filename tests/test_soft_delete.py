"""App-wide soft-delete: cascade, restore, admin-only visibility, caching.

Covers the behavior added across this branch's commits:
- deleting cascades via deactivate_with_cascade() along CASCADE FK edges only
  (PROTECT/SET_NULL relations are left untouched)
- default visibility is active-only for everyone, including admins; admin
  widens only with ?include_inactive=true
- the restore action (admin-only) does not cascade
- deleting a DoctorProfile also disables the linked User's login; restoring
  the profile does not reactivate the User
- MedicalCenterViewSet's doctor_count annotation survives the all_objects
  queryset swap
- CachedListViewMixin bypasses the cache for admin include_inactive requests
- Django-admin delete_model soft-deletes instead of hard-deleting, and bulk
  "Delete selected" is removed
"""

from django.contrib.admin.sites import AdminSite
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile, DoctorSchedule
from apps.medicines.models import Medicine
from apps.patients.models import Patient
from apps.records.models import ConsultationLog, MedicalRecord, RecordImage


def _patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "phone": "8095550100",
        "cedula": "00112345678",
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _center(code="C1"):
    return MedicalCenter.objects.create(
        name=f"Center {code}", code=code, address="A", phone="1"
    )


def _doctor_profile(user, license_suffix=None):
    return DoctorProfile.objects.create(
        user=user,
        specialty="Cardiology",
        license_number=f"LIC-{license_suffix or user.id}",
        contact_phone="8095550000",
        contact_email="doc@example.com",
    )


def _record(patient, user, center=None, title="R"):
    return MedicalRecord.objects.create(
        patient=patient, created_by=user, title=title, diagnosis="d", center=center
    )


def _appointment(patient, doctor_profile, created_by):
    return Appointment.objects.create(
        patient=patient,
        doctor=doctor_profile,
        date_time="2026-09-01T10:00:00Z",
        created_by=created_by,
    )


# ---------------------------------------------------------------------------
# Cascade: Patient -> MedicalRecord -> RecordImage, ConsultationLog, Appointment
# ---------------------------------------------------------------------------


def test_deleting_patient_cascades_to_records_logs_appointments_and_images(
    auth_client, admin_user, receptionist_user, doctor_user
):
    patient = _patient()
    doctor = _doctor_profile(doctor_user)
    record = _record(patient, receptionist_user)
    image = RecordImage.objects.create(record=record, image="test.jpg", caption="x")
    log = ConsultationLog.objects.create(patient=patient, doctor=doctor_user)
    appointment = _appointment(patient, doctor, receptionist_user)

    res = auth_client(admin_user).delete(f"/api/patients/{patient.id}/")
    assert res.status_code == 204, res.data

    patient.refresh_from_db()
    record.refresh_from_db()
    image.refresh_from_db()
    log.refresh_from_db()
    appointment.refresh_from_db()
    assert patient.active is False
    assert record.active is False
    assert image.active is False
    assert log.active is False
    assert appointment.active is False


def test_deleting_doctor_does_not_cascade_to_appointments(
    auth_client, admin_user, receptionist_user, doctor_user
):
    """Appointment.doctor is PROTECT, not CASCADE -- deactivating a doctor
    must not touch their existing appointments."""
    patient = _patient()
    doctor = _doctor_profile(doctor_user)
    appointment = _appointment(patient, doctor, receptionist_user)

    res = auth_client(admin_user).delete(f"/api/doctors/profiles/{doctor.id}/")
    assert res.status_code == 204, res.data

    appointment.refresh_from_db()
    assert appointment.active is True


# ---------------------------------------------------------------------------
# Doctor deletion also disables login; restore does not reactivate the user
# ---------------------------------------------------------------------------


def test_deleting_doctor_cascades_to_schedule_binding_and_disables_login(
    auth_client, admin_user, doctor_user
):
    doctor = _doctor_profile(doctor_user)
    center = _center()
    schedule = DoctorSchedule.objects.create(
        doctor=doctor,
        center=center,
        weekday=0,
        start_time="09:00",
        end_time="12:00",
    )
    binding = DoctorCenterBinding.objects.create(doctor=doctor, center=center)

    assert doctor_user.is_active is True

    res = auth_client(admin_user).delete(f"/api/doctors/profiles/{doctor.id}/")
    assert res.status_code == 204, res.data

    doctor.refresh_from_db()
    schedule.refresh_from_db()
    binding.refresh_from_db()
    doctor_user.refresh_from_db()
    assert doctor.active is False
    assert schedule.active is False
    assert binding.active is False
    assert doctor_user.is_active is False

    # Login is blocked for the deactivated doctor.
    anon = APIClient()
    login_res = anon.post(
        "/api/auth/login/",
        {"username": doctor_user.username, "password": "pass12345"},
        format="json",
    )
    assert login_res.status_code == 401, login_res.data


def test_restoring_doctor_profile_does_not_reactivate_user(
    auth_client, admin_user, doctor_user
):
    doctor = _doctor_profile(doctor_user)
    auth_client(admin_user).delete(f"/api/doctors/profiles/{doctor.id}/")
    doctor_user.refresh_from_db()
    assert doctor_user.is_active is False

    res = auth_client(admin_user).post(f"/api/doctors/profiles/{doctor.id}/restore/")
    assert res.status_code == 200, res.data

    doctor.refresh_from_db()
    doctor_user.refresh_from_db()
    assert doctor.active is True
    assert doctor_user.is_active is False  # asymmetric restore, by design


# ---------------------------------------------------------------------------
# Visibility: default active-only for everyone; admin widens explicitly
# ---------------------------------------------------------------------------


def test_non_admin_never_sees_inactive_even_with_include_inactive(
    auth_client, receptionist_user, admin_user
):
    patient = _patient()
    auth_client(admin_user).delete(f"/api/patients/{patient.id}/")

    res = auth_client(receptionist_user).get("/api/patients/?include_inactive=true")
    assert res.status_code == 200
    assert res.data["count"] == 0


def test_admin_sees_inactive_only_with_include_inactive(auth_client, admin_user):
    patient = _patient()
    auth_client(admin_user).delete(f"/api/patients/{patient.id}/")

    default_res = auth_client(admin_user).get("/api/patients/")
    assert default_res.data["count"] == 0

    widened_res = auth_client(admin_user).get("/api/patients/?include_inactive=true")
    assert widened_res.data["count"] == 1
    assert widened_res.data["results"][0]["active"] is False


# ---------------------------------------------------------------------------
# Restore action: permission-gated, does not cascade
# ---------------------------------------------------------------------------


def test_restore_forbidden_for_non_admin(auth_client, receptionist_user, admin_user):
    patient = _patient()
    auth_client(admin_user).delete(f"/api/patients/{patient.id}/")

    res = auth_client(receptionist_user).post(f"/api/patients/{patient.id}/restore/")
    assert res.status_code == 403, res.data


def test_restore_does_not_cascade_to_children(
    auth_client, admin_user, receptionist_user
):
    patient = _patient()
    record = _record(patient, receptionist_user)
    auth_client(admin_user).delete(f"/api/patients/{patient.id}/")
    record.refresh_from_db()
    assert record.active is False

    res = auth_client(admin_user).post(f"/api/patients/{patient.id}/restore/")
    assert res.status_code == 200, res.data

    patient.refresh_from_db()
    record.refresh_from_db()
    assert patient.active is True
    assert record.active is False  # not auto-restored


# ---------------------------------------------------------------------------
# MedicalCenterViewSet's doctor_count annotation survives all_objects
# ---------------------------------------------------------------------------


def test_medical_center_doctor_count_annotation_survives_include_inactive(
    auth_client, admin_user, doctor_user
):
    center = _center()
    doctor = _doctor_profile(doctor_user)
    DoctorCenterBinding.objects.create(doctor=doctor, center=center, approved=True)

    res = auth_client(admin_user).get("/api/centers/?include_inactive=true")
    assert res.status_code == 200, res.data
    row = next(r for r in res.data["results"] if r["id"] == center.id)
    assert row["doctor_count"] == 1


# ---------------------------------------------------------------------------
# Caching bypass for admin include_inactive requests
# ---------------------------------------------------------------------------


def test_cached_list_bypasses_cache_for_admin_include_inactive(
    auth_client, admin_user
):
    med = Medicine.objects.create(generic_name="A", commercial_name="B")
    auth_client(admin_user).delete(f"/api/medicines/{med.id}/")

    # Widened admin view: must reflect the deactivation immediately, not a
    # stale cached active-only response.
    res = auth_client(admin_user).get("/api/medicines/?include_inactive=true")
    assert res.data["count"] == 1
    assert res.data["results"][0]["active"] is False


def test_cached_list_still_caches_normal_path(auth_client, receptionist_user):
    from django.core.cache import cache
    from django.test import RequestFactory

    from apps.core.caching import list_cache_key

    Medicine.objects.create(generic_name="A", commercial_name="B")
    first = auth_client(receptionist_user).get("/api/medicines/")
    assert first.data["count"] == 1

    # Plant a distinguishable fake payload directly under the same cache key
    # the mixin would have used, and confirm a second normal-path request
    # returns it verbatim -- proof it's actually reading from cache rather
    # than hitting the DB every time (a .save() bump of the version counter
    # would invalidate this too, so this has to bypass the DB entirely).
    key = list_cache_key("medicine", RequestFactory().get("/api/medicines/"))
    cache.set(key, {"count": 999, "results": []}, timeout=300)

    second = auth_client(receptionist_user).get("/api/medicines/")
    assert second.data["count"] == 999


# ---------------------------------------------------------------------------
# Django-admin parity: delete_model soft-deletes, bulk delete is removed
# ---------------------------------------------------------------------------


class _StubRequest:
    """Minimal stand-in for a Django admin request: enough for delete_model()
    (request.user, request.META, via log_audit()/client_ip()) and
    get_actions() (request.GET, checked against the popup-window var) to not
    blow up."""

    def __init__(self, user):
        self.user = user
        self.META = {}
        self.GET = {}


def test_admin_delete_model_soft_deletes(admin_user):
    med = Medicine.objects.create(generic_name="A", commercial_name="B")
    from apps.medicines.admin import MedicineAdmin

    site = AdminSite()
    ma = MedicineAdmin(Medicine, site)
    ma.delete_model(_StubRequest(admin_user), med)

    med.refresh_from_db()
    assert med.active is False
    assert Medicine.objects.filter(pk=med.pk).exists() is False
    assert Medicine.all_objects.filter(pk=med.pk).exists() is True


def test_admin_bulk_delete_selected_action_removed(admin_user):
    from apps.medicines.admin import MedicineAdmin

    site = AdminSite()
    ma = MedicineAdmin(Medicine, site)
    actions = ma.get_actions(_StubRequest(admin_user))
    assert "delete_selected" not in actions
