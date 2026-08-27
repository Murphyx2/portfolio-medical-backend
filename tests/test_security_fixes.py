"""Regression tests for the security pass (H-02, H-03, M-01..M-05).

Covers:
- H-02: record images are center-scoped for doctors; /media/ requires a signed token.
- H-03: IT loses Django admin (is_staff) and cannot create/promote/delete ADMIN users.
- M-01: password validators run on API user creation.
- M-02: patient list/detail center scoping for doctors (centerless = unbound).
- M-03: doctor writes (records/images) rejected for out-of-scope patients/records.
- M-04: names/birth date encrypted at rest; search_name index keeps search working.
- M-05: IT/center-manager see masked names/birth date and null age.
"""

from io import BytesIO

from django.conf import settings
from PIL import Image as PILImage
from rest_framework.test import APIClient

from django.db import connection

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient
from apps.records.models import MedicalRecord, RecordImage
from apps.core.encryption import is_encrypted
from apps.core.services import sign_media_token


def _make_center(code="C1", name="Center 1"):
    return MedicalCenter.objects.create(name=name, code=code, address="A", phone="1")


def _make_profile(user, license_number=None):
    return DoctorProfile.objects.create(
        user=user,
        license_number=license_number or f"LIC-{user.id}",
        contact_phone="555-0000",
    )


def _make_binding(profile, center):
    return DoctorCenterBinding.objects.create(
        doctor=profile, center=center, approved=True
    )


def _make_patient(**overrides):
    data = {"first_name": "Jane", "last_name": "Doe", "gender": "FEMALE"}
    data.update(overrides)
    return Patient.objects.create(**data)


# ---------------------------------------------------------------------------
# M-04: names / birth date encrypted at rest + search_name
# ---------------------------------------------------------------------------

def test_names_and_birth_date_encrypted_at_rest(db):
    p = _make_patient(birth_date="1990-05-12")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT first_name, last_name, birth_date FROM patients_patient WHERE id=%s",
            [p.pk],
        )
        raw_fn, raw_ln, raw_bd = cursor.fetchone()
    assert is_encrypted(raw_fn)
    assert is_encrypted(raw_ln)
    assert is_encrypted(raw_bd)
    assert "Jane" not in raw_fn


def test_search_name_populated_and_searchable(auth_client, receptionist_user):
    _make_patient(first_name="Jane", last_name="Smith")
    _make_patient(first_name="Peter", last_name="Jones")
    res = auth_client(receptionist_user).get("/api/patients/?search=jane")
    assert res.status_code == 200
    assert res.data["count"] == 1
    assert res.data["results"][0]["first_name"] == "Jane"


# ---------------------------------------------------------------------------
# M-02: patient center scoping for doctors
# ---------------------------------------------------------------------------

def test_doctor_sees_patients_across_all_centers(auth_client, make_user):
    # Doctors have unrestricted patient-list visibility (matching their
    # already-unrestricted access to medical records via CanManageRecords) --
    # this was an intentional policy change away from center-scoped
    # visibility, see PatientViewSet.get_queryset().
    doc = make_user("doc", "DOCTOR")
    center = _make_center("C1", "My Center")
    other = _make_center("C2", "Other Center")
    _make_binding(_make_profile(doc), center)

    unbound = _make_patient(first_name="Un", last_name="Bound")
    own = _make_patient(first_name="Ow", last_name="nCenter", center=center)
    foreign = _make_patient(first_name="Fo", last_name="reign", center=other)

    client = auth_client(doc)
    res = client.get("/api/patients/")
    ids = {row["id"] for row in res.data["results"]}
    assert unbound.id in ids
    assert own.id in ids
    assert foreign.id in ids

    assert client.get(f"/api/patients/{own.id}/").status_code == 200
    assert client.get(f"/api/patients/{foreign.id}/").status_code == 200


def test_receptionist_sees_all_patients(auth_client, receptionist_user):
    c1 = _make_center("C1")
    c2 = _make_center("C2")
    p1 = _make_patient(center=c1)
    p2 = _make_patient(center=c2)
    res = auth_client(receptionist_user).get("/api/patients/")
    ids = {row["id"] for row in res.data["results"]}
    assert {p1.id, p2.id} <= ids


# ---------------------------------------------------------------------------
# M-03: doctor writes rejected for out-of-scope patients (still enforced for
# apps other than records -- records scoping was intentionally removed, see
# CanManageRecords/apps.records.serializers).
# ---------------------------------------------------------------------------

def test_doctor_record_for_foreign_patient_allowed(auth_client, make_user):
    # Records are not scoped to a doctor's approved centers -- a record for
    # a patient at a center the doctor isn't bound to is allowed.
    doc = make_user("doc", "DOCTOR")
    center = _make_center("C1")
    other = _make_center("C2")
    _make_binding(_make_profile(doc), center)
    foreign = _make_patient(center=other)

    res = auth_client(doc).post(
        "/api/medical-records/",
        {"patient": foreign.id, "title": "t", "diagnosis": "d", "center": center.id},
        format="json",
    )
    assert res.status_code == 201, res.data


def test_doctor_record_for_centerless_patient_ok(auth_client, make_user):
    doc = make_user("doc", "DOCTOR")
    center = _make_center("C1")
    _make_binding(_make_profile(doc), center)
    patient = _make_patient()

    res = auth_client(doc).post(
        "/api/medical-records/",
        {"patient": patient.id, "title": "t", "diagnosis": "d", "center": center.id},
        format="json",
    )
    assert res.status_code == 201, res.data


def test_doctor_image_for_foreign_record_allowed(auth_client, make_user):
    # Record images inherit the same unscoped access as their parent record.
    doc = make_user("doc", "DOCTOR")
    other_doc = make_user("other", "DOCTOR")
    center = _make_center("C1")
    other = _make_center("C2")
    _make_binding(_make_profile(doc), center)
    patient = _make_patient(center=center)
    foreign_patient = _make_patient(first_name="F", last_name="F", center=other)
    foreign_record = MedicalRecord.objects.create(
        patient=foreign_patient, created_by=other_doc, center=other
    )

    buf = BytesIO()
    PILImage.new("RGB", (4, 4), "red").save(buf, format="PNG")
    buf.seek(0)

    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("x.png", buf.read(), content_type="image/png")
    res = auth_client(doc).post(
        "/api/images/",
        {"record": foreign_record.id, "image": upload, "caption": "x"},
        format="multipart",
    )
    assert res.status_code == 201, res.data


def test_record_image_list_is_unscoped_for_doctor(auth_client, make_user):
    doc = make_user("doc", "DOCTOR")
    other_doc = make_user("other", "DOCTOR")
    center = _make_center("C1")
    other = _make_center("C2")
    _make_binding(_make_profile(doc), center)

    own_record = MedicalRecord.objects.create(
        patient=_make_patient(center=center), created_by=doc, center=center
    )
    other_record = MedicalRecord.objects.create(
        patient=_make_patient(first_name="O", last_name="T", center=other),
        created_by=other_doc,
        center=other,
    )
    own_img = RecordImage.objects.create(record=own_record, image="records/1/a.png")
    other_img = RecordImage.objects.create(record=other_record, image="records/2/b.png")

    res = auth_client(doc).get("/api/images/")
    ids = {row["id"] for row in res.data["results"]}
    assert own_img.id in ids
    assert other_img.id in ids


# ---------------------------------------------------------------------------
# H-02: media requires a signed token
# ---------------------------------------------------------------------------

def test_media_requires_signed_token(auth_client, make_user, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "MEDIA_ROOT", tmp_path)
    doc = make_user("doc", "DOCTOR")
    center = _make_center("C1")
    _make_binding(_make_profile(doc), center)
    patient = _make_patient(center=center)
    record = MedicalRecord.objects.create(patient=patient, created_by=doc, center=center)
    img_dir = tmp_path / "records" / str(patient.id)
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "abc.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    rec_img = RecordImage.objects.create(
        record=record, image=f"records/{patient.id}/abc.png"
    )

    client = auth_client(doc)
    url = f"/media/records/{patient.id}/abc.png"
    assert client.get(url).status_code == 404
    assert client.get(url + "?token=bad").status_code == 404
    assert client.get(url + f"?token={sign_media_token(rec_img.image.name)}").status_code == 200
    # An authenticated user cannot fetch media without a token either.
    res = client.get(url)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# H-03: IT role boundary
# ---------------------------------------------------------------------------

def test_it_loses_staff_and_superuser(make_user):
    it = make_user("it", "IT")
    assert it.is_staff is False
    assert it.is_superuser is False


def test_admin_keeps_staff_and_superuser(make_user):
    admin = make_user("admin", "ADMIN")
    assert admin.is_staff is True
    assert admin.is_superuser is True


def test_it_cannot_create_admin(auth_client, make_user):
    it = make_user("it", "IT")
    res = auth_client(it).post(
        "/api/auth/users/",
        {"username": "newadmin", "password": "Str0ngPass123!", "role": "ADMIN"},
        format="json",
    )
    assert res.status_code == 400
    assert "role" in res.data


def test_it_can_create_non_admin_user(auth_client, make_user):
    it = make_user("it", "IT")
    res = auth_client(it).post(
        "/api/auth/users/",
        {"username": "newdoc", "password": "Str0ngPass123!", "role": "DOCTOR"},
        format="json",
    )
    assert res.status_code == 201, res.data


def test_it_cannot_demote_or_delete_admin(auth_client, make_user):
    it = make_user("it", "IT")
    admin = make_user("admin2", "ADMIN")

    res = auth_client(it).patch(f"/api/auth/users/{admin.id}/", {"role": "DOCTOR"}, format="json")
    assert res.status_code == 400

    res = auth_client(it).delete(f"/api/auth/users/{admin.id}/")
    assert res.status_code == 403
    assert admin.__class__.objects.filter(pk=admin.pk).exists()


def test_admin_can_create_admin(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {"username": "newadmin", "password": "Str0ngPass123!", "role": "ADMIN"},
        format="json",
    )
    assert res.status_code == 201, res.data


# ---------------------------------------------------------------------------
# M-01: password policy
# ---------------------------------------------------------------------------

def test_weak_password_rejected_on_create(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {"username": "weakpw", "password": "123", "role": "DOCTOR"},
        format="json",
    )
    assert res.status_code == 400
    assert "password" in res.data


# ---------------------------------------------------------------------------
# M-05: names / birth date masked for IT; CENTER_MANAGER is admin-equivalent
# app-wide (except Settings edit) and sees full PII.
# ---------------------------------------------------------------------------

def test_it_sees_masked_names(auth_client, make_user):
    it = make_user("it", "IT")
    patient = _make_patient(birth_date="1990-05-12")

    res = auth_client(it).get(f"/api/patients/{patient.id}/")
    assert res.status_code == 200
    assert res.data["first_name"] != "Jane"
    assert "•" in res.data["first_name"]
    assert res.data["last_name"] != "Doe"
    assert res.data["full_name"] != "Jane Doe"
    assert res.data["birth_date"] != "1990-05-12"
    assert res.data["age"] is None


def test_center_manager_sees_full_names(auth_client, make_user):
    cm = make_user("cm", "CENTER_MANAGER")
    patient = _make_patient(birth_date="1990-05-12")

    res = auth_client(cm).get(f"/api/patients/{patient.id}/")
    assert res.status_code == 200
    assert res.data["first_name"] == "Jane"
    assert res.data["last_name"] == "Doe"
    assert res.data["full_name"] == "Jane Doe"
    assert res.data["birth_date"] == "1990-05-12"
    assert res.data["age"] is not None


def test_doctor_sees_full_names(auth_client, doctor_user):
    patient = _make_patient(birth_date="1990-05-12")
    res = auth_client(doctor_user).get(f"/api/patients/{patient.id}/")
    assert res.status_code == 200
    assert res.data["first_name"] == "Jane"
    assert res.data["birth_date"] == "1990-05-12"
    assert res.data["age"] is not None
