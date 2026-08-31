"""Direct unit tests for the security-invariant helper functions that today
are only reachable through the full HTTP-integration suite (B9 of
ARCHITECTURE_REFACTOR_PLAN.md). These pin current behavior at the function
level so B1/B2-style refactors of the same logic can be verified identical
without re-deriving a 50-line HTTP scenario for a 3-line rule.
"""

from datetime import date

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.centers.models import DoctorCenterBinding, MedicalCenter
from apps.core.masking import apply_masking, mask_doctor_contact
from apps.core.permissions import is_owner_doctor
from apps.core.services import (
    can_view_inactive,
    can_write_center,
    client_ip,
    deactivate_with_cascade,
    is_masked_role,
    is_own_doctor_relation,
    log_audit,
    program_belongs_to_ars,
    scope_queryset,
    soft_delete_field_name,
    user_accessible_center_ids,
    verify_media_token,
    sign_media_token,
)
from apps.doctors.models import DoctorProfile
from apps.encounters.filters import EncounterSearchFilter
from apps.encounters.models import Encounter
from apps.encounters.serializers import _sync_related
from apps.patients.filters import PatientSearchFilter
from apps.patients.models import Patient
from apps.records.filters import RecordSearchFilter
from apps.records.models import MedicalRecord
from apps.rooms.models import Room, RoomType
from apps.services.models import ServiceType


def _make_patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "birth_date": "1990-01-01",
        "gender": "FEMALE",
        "cedula": "00112345678",
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _make_center(**overrides):
    data = {"name": "Main", "code": "C1", "address": "123 St", "phone": "8095551111"}
    data.update(overrides)
    return MedicalCenter.objects.create(**data)


def _make_doctor(user, **overrides):
    data = {"license_number": f"LIC-{user.id}", "contact_phone": "8095550000"}
    data.update(overrides)
    return DoctorProfile.objects.create(user=user, **data)


def _make_service_type(**overrides):
    data = {"name": "Consulta", "requires_doctor": False}
    data.update(overrides)
    return ServiceType.objects.get_or_create(
        name=data.pop("name").upper(), defaults=data
    )[0]


def _make_room(center, **overrides):
    room_type = RoomType.objects.get_or_create(name="CONSULT")[0]
    data = {"code": f"R{center.pk}", "name": "Room 1", "room_type": room_type, "center": center}
    data.update(overrides)
    return Room.objects.create(**data)


def _make_encounter(patient, created_by, **overrides):
    data = {"service_type": _make_service_type(), "patient": patient, "created_by": created_by}
    data.update(overrides)
    return Encounter.objects.create(**data)


def _search_request(user, term):
    factory_request = APIRequestFactory().get("/", {"search": term})
    request = Request(factory_request)
    request.user = user
    return request


# ---------------------------------------------------------------------------
# user_accessible_center_ids / scope_queryset
# ---------------------------------------------------------------------------


def test_user_accessible_center_ids_admin_is_unrestricted(admin_user):
    assert user_accessible_center_ids(admin_user) == set()


def test_user_accessible_center_ids_non_doctor_staff_is_empty(receptionist_user):
    assert user_accessible_center_ids(receptionist_user) == set()


def test_user_accessible_center_ids_unauthenticated_is_empty():
    from django.contrib.auth.models import AnonymousUser

    assert user_accessible_center_ids(AnonymousUser()) == set()


def test_user_accessible_center_ids_doctor_scoped_to_approved_bindings(doctor_user):
    doctor = _make_doctor(doctor_user)
    approved_center = _make_center(code="C-APR")
    unapproved_center = _make_center(code="C-UNAPR")
    DoctorCenterBinding.objects.create(doctor=doctor, center=approved_center, approved=True)
    DoctorCenterBinding.objects.create(doctor=doctor, center=unapproved_center, approved=False)

    assert user_accessible_center_ids(doctor_user) == {approved_center.id}


def test_scope_queryset_non_doctor_is_unfiltered(admin_user, receptionist_user):
    center = _make_center()
    patient_in_center = _make_patient(cedula="00112345671", center=center)
    patient_no_center = _make_patient(cedula="00112345672")

    qs = scope_queryset(Patient.objects.all(), admin_user)
    assert set(qs.values_list("id", flat=True)) == {
        patient_in_center.id,
        patient_no_center.id,
    }

    qs = scope_queryset(Patient.objects.all(), receptionist_user)
    assert set(qs.values_list("id", flat=True)) == {
        patient_in_center.id,
        patient_no_center.id,
    }


def test_scope_queryset_doctor_sees_only_approved_center_rows(doctor_user):
    doctor = _make_doctor(doctor_user)
    approved_center = _make_center(code="C-APR2")
    other_center = _make_center(code="C-OTHER")
    DoctorCenterBinding.objects.create(doctor=doctor, center=approved_center, approved=True)

    visible = _make_patient(cedula="00112345673", center=approved_center)
    hidden = _make_patient(cedula="00112345674", center=other_center)

    qs = scope_queryset(Patient.objects.all(), doctor_user)
    ids = set(qs.values_list("id", flat=True))
    assert visible.id in ids
    assert hidden.id not in ids


def test_scope_queryset_doctor_owner_field_adds_owned_rows(doctor_user):
    """A doctor with no approved bindings still sees rows they own via
    owner_field, not nothing."""
    other_center = _make_center(code="C-OWNER-OTHER")
    owned_patient = _make_patient(cedula="00112345675")
    other_patient = _make_patient(cedula="00112345676", center=other_center)
    record = MedicalRecord.objects.create(patient=owned_patient, created_by=doctor_user)
    other_record = MedicalRecord.objects.create(patient=other_patient, created_by=doctor_user)

    qs = scope_queryset(
        MedicalRecord.objects.all(), doctor_user, center_field="patient__center", owner_field="created_by"
    )
    ids = set(qs.values_list("id", flat=True))
    assert record.id in ids
    assert other_record.id in ids  # owned via created_by, despite no center binding


# ---------------------------------------------------------------------------
# is_masked_role / can_view_inactive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role_fixture,expected",
    [
        ("admin_user", False),
        ("doctor_user", False),
        ("nurse_user", False),
        ("receptionist_user", False),
        ("it_user", True),
        ("center_manager_user", False),
    ],
)
def test_is_masked_role_per_role(request, role_fixture, expected):
    user = request.getfixturevalue(role_fixture)
    assert is_masked_role(user) is expected


def test_is_masked_role_unauthenticated_is_false():
    from django.contrib.auth.models import AnonymousUser

    assert is_masked_role(AnonymousUser()) is False


def test_can_view_inactive_only_admin(admin_user, doctor_user, it_user):
    assert can_view_inactive(admin_user) is True
    assert can_view_inactive(doctor_user) is False
    assert can_view_inactive(it_user) is False


# ---------------------------------------------------------------------------
# soft_delete_field_name / deactivate_with_cascade
# ---------------------------------------------------------------------------


def test_soft_delete_field_name(admin_user):
    assert soft_delete_field_name(Patient) == "active"
    assert soft_delete_field_name(type(admin_user)) == "is_active"
    assert soft_delete_field_name(dict) is None


def test_deactivate_with_cascade_cascades_to_related_soft_deletable_rows(doctor_user):
    """MedicalRecord.patient is on_delete=CASCADE (unlike Encounter.patient,
    which is PROTECT) -- it's the genuine cascade edge off Patient."""
    patient = _make_patient()
    record = MedicalRecord.objects.create(patient=patient, created_by=doctor_user)
    assert patient.active is True
    assert record.active is True

    deactivate_with_cascade(patient)

    patient.refresh_from_db()
    record.refresh_from_db()
    assert patient.active is False
    assert record.active is False


def test_deactivate_with_cascade_is_idempotent(doctor_user):
    patient = _make_patient()
    deactivate_with_cascade(patient)
    patient.refresh_from_db()
    assert patient.active is False

    # Second call must no-op, not raise, even with a fresh `seen` set.
    deactivate_with_cascade(patient)
    patient.refresh_from_db()
    assert patient.active is False


def test_deactivate_with_cascade_stops_at_protect_relations(doctor_user):
    """Encounter.patient is on_delete=PROTECT, not CASCADE -- it (and
    anything reachable only through it, like service_type) must be left
    untouched by cascading through the patient."""
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)
    service_type = encounter.service_type

    deactivate_with_cascade(patient)

    encounter.refresh_from_db()
    service_type.refresh_from_db()
    assert encounter.active is True
    assert service_type.active is True


# ---------------------------------------------------------------------------
# log_audit / client_ip
# ---------------------------------------------------------------------------


def test_log_audit_creates_entry_with_target_derived_type_and_id(admin_user):
    patient = _make_patient()
    entry = log_audit(user=admin_user, action="create", target=patient, ip_address="1.2.3.4")

    assert entry.user_id == admin_user.id
    assert entry.action == "create"
    assert entry.target_type == "Patient"
    assert entry.target_id == patient.pk
    assert entry.ip_address == "1.2.3.4"
    assert entry.details == {}


def test_log_audit_unauthenticated_user_stored_as_none(db):
    from django.contrib.auth.models import AnonymousUser

    entry = log_audit(user=AnonymousUser(), action="login_failed")
    assert entry.user_id is None


def test_client_ip_prefers_forwarded_for():
    request = APIRequestFactory().get("/")
    request.META["HTTP_X_FORWARDED_FOR"] = "9.9.9.9, 10.0.0.1"
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    assert client_ip(request) == "9.9.9.9"


def test_client_ip_falls_back_to_remote_addr():
    request = APIRequestFactory().get("/")
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    assert client_ip(request) == "127.0.0.1"


# ---------------------------------------------------------------------------
# verify_media_token
# ---------------------------------------------------------------------------


def test_verify_media_token_round_trip():
    token = sign_media_token("records/1/x.png")
    assert verify_media_token("records/1/x.png", token) is True


def test_verify_media_token_rejects_mismatched_path():
    token = sign_media_token("records/1/x.png")
    assert verify_media_token("records/2/other.png", token) is False


def test_verify_media_token_rejects_expired_token():
    token = sign_media_token("records/1/x.png")
    assert verify_media_token("records/1/x.png", token, max_age=0) is False


def test_verify_media_token_rejects_garbage_token():
    assert verify_media_token("records/1/x.png", "not-a-valid-token") is False


# ---------------------------------------------------------------------------
# apply_masking
# ---------------------------------------------------------------------------


def test_apply_masking_no_op_for_unauthenticated_user():
    data = {"phone": "8095551234"}
    from django.contrib.auth.models import AnonymousUser

    result = apply_masking(data, AnonymousUser(), masked_fields=("phone",))
    assert result == {"phone": "8095551234"}


def test_apply_masking_masks_fields_for_masked_role(it_user):
    data = {"phone": "8095551234", "notes": "keep"}
    result = apply_masking(data, it_user, masked_fields=("phone",))
    assert result is data  # mutated in place and returned
    assert result["phone"] == "80••••34"
    assert result["notes"] == "keep"


def test_apply_masking_masked_nulls_for_masked_role(it_user):
    data = {"email": "a@b.com"}
    apply_masking(data, it_user, masked_nulls=("email",))
    assert data["email"] is None


def test_apply_masking_does_not_touch_unmasked_role(doctor_user):
    data = {"phone": "8095551234"}
    apply_masking(data, doctor_user, masked_fields=("phone",))
    assert data["phone"] == "8095551234"


def test_apply_masking_masked_nested_subfields(it_user):
    data = {"patient_info": {"cedula": "00112345678", "keep": "x"}}
    apply_masking(data, it_user, masked_nested=(("patient_info", ("cedula",)),))
    assert data["patient_info"]["cedula"] == "00••••78"
    assert data["patient_info"]["keep"] == "x"


def test_apply_masking_clinical_fields_masked_for_non_clinical_role(receptionist_user):
    """Receptionist is masked-role=False but also not a clinical role, so the
    clinical-narrative branch applies independently of the masked-role one."""
    data = {"diagnosis": "Hypertension detail"}
    apply_masking(data, receptionist_user, clinical_fields=("diagnosis",))
    assert data["diagnosis"] == "Hy••••il"


def test_apply_masking_clinical_fields_untouched_for_clinical_role(doctor_user, nurse_user, admin_user):
    for user in (doctor_user, nurse_user, admin_user):
        data = {"diagnosis": "Hypertension detail"}
        apply_masking(data, user, clinical_fields=("diagnosis",))
        assert data["diagnosis"] == "Hypertension detail"


def test_apply_masking_clinical_nested(receptionist_user):
    data = {"diagnoses": [{"description": "Long diagnosis text"}, {"description": "short"}]}
    apply_masking(data, receptionist_user, clinical_nested=(("diagnoses", ("description",)),))
    assert data["diagnoses"][0]["description"] == "Lo••••xt"
    assert data["diagnoses"][1]["description"] == "sh••••rt"


# ---------------------------------------------------------------------------
# mask_doctor_contact
# ---------------------------------------------------------------------------


def test_mask_doctor_contact_admin_sees_everything(admin_user, doctor_user):
    doctor = _make_doctor(doctor_user, contact_email="doc@x.com", bio="Bio text")
    data = {
        "license_number": doctor.license_number,
        "contact_phone": doctor.contact_phone,
        "contact_email": doctor.contact_email,
        "bio": doctor.bio,
    }
    result = mask_doctor_contact(dict(data), admin_user, doctor)
    assert result == data


def test_mask_doctor_contact_self_view_sees_everything(doctor_user):
    doctor = _make_doctor(doctor_user, bio="Bio text")
    data = {"license_number": doctor.license_number, "contact_phone": doctor.contact_phone, "bio": doctor.bio}
    result = mask_doctor_contact(dict(data), doctor_user, doctor)
    assert result == data


def test_mask_doctor_contact_receptionist_keeps_phone_email_masks_license_and_bio(
    doctor_user, receptionist_user
):
    doctor = _make_doctor(doctor_user, contact_email="doc@x.com", bio="Bio text")
    data = {
        "license_number": doctor.license_number,
        "contact_phone": doctor.contact_phone,
        "contact_email": doctor.contact_email,
        "bio": doctor.bio,
    }
    result = mask_doctor_contact(dict(data), receptionist_user, doctor)
    assert result["contact_phone"] == doctor.contact_phone
    assert result["contact_email"] == doctor.contact_email
    assert result["license_number"] != doctor.license_number
    assert result["bio"] is None


def test_mask_doctor_contact_other_staff_masks_phone_email_license_bio(doctor_user, nurse_user):
    doctor = _make_doctor(doctor_user, contact_email="doc@x.com", bio="Bio text")
    data = {
        "license_number": doctor.license_number,
        "contact_phone": doctor.contact_phone,
        "contact_email": doctor.contact_email,
        "bio": doctor.bio,
    }
    result = mask_doctor_contact(dict(data), nurse_user, doctor)
    assert result["contact_phone"] != doctor.contact_phone
    assert result["contact_email"] != doctor.contact_email
    assert result["license_number"] != doctor.license_number
    assert result["bio"] is None


# ---------------------------------------------------------------------------
# Encounter.ready_for_active
# ---------------------------------------------------------------------------


def test_ready_for_active_requires_room(doctor_user):
    from apps.services.models import Service

    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)
    service = Service.objects.create(
        simon="100010", name="Ready room test", type=encounter.service_type, co_pago=0, privado=0
    )
    encounter.services.create(service=service)
    errors = encounter.ready_for_active()
    assert "A room is required to admit this encounter." in errors


def test_ready_for_active_does_not_require_a_diagnosis(doctor_user):
    # Diagnosis capture was removed from the admission flow entirely --
    # ready_for_active() never checks for a diagnosis at all.
    from apps.services.models import Service

    center = _make_center(code="C-READY1")
    room = _make_room(center)
    patient = _make_patient()
    encounter = _make_encounter(
        patient,
        doctor_user,
        service_type=_make_service_type(name="Needs Dx"),
    )
    service = Service.objects.create(
        simon="100011", name="Ready no dx test", type=encounter.service_type, co_pago=0, privado=0
    )
    encounter.services.create(service=service, room=room)
    assert encounter.ready_for_active() == []


# ---------------------------------------------------------------------------
# _sync_related
# ---------------------------------------------------------------------------


def test_sync_related_creates_new_items(doctor_user):
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)

    _sync_related(
        encounter.diagnoses,
        [{"description": "Flu", "is_primary": True}],
        is_valid=lambda item: bool(item.get("description")),
        build_fields=lambda item: {
            "description": item["description"],
            "is_primary": item.get("is_primary", False),
        },
    )

    assert encounter.diagnoses.count() == 1
    assert encounter.diagnoses.first().description == "Flu"


def test_sync_related_updates_matching_id_in_place(doctor_user):
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)
    existing = encounter.diagnoses.create(description="Old", is_primary=False)

    _sync_related(
        encounter.diagnoses,
        [{"id": existing.pk, "description": "Updated", "is_primary": True}],
        is_valid=lambda item: bool(item.get("description")),
        build_fields=lambda item: {
            "description": item["description"],
            "is_primary": item.get("is_primary", False),
        },
    )

    existing.refresh_from_db()
    assert existing.description == "Updated"
    assert existing.is_primary is True
    assert encounter.diagnoses.count() == 1


def test_sync_related_deletes_rows_not_resubmitted(doctor_user):
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)
    keep = encounter.diagnoses.create(description="Keep", is_primary=False)
    encounter.diagnoses.create(description="Drop", is_primary=False)

    _sync_related(
        encounter.diagnoses,
        [{"id": keep.pk, "description": "Keep", "is_primary": False}],
        is_valid=lambda item: bool(item.get("description")),
        build_fields=lambda item: {
            "description": item["description"],
            "is_primary": item.get("is_primary", False),
        },
    )

    assert list(encounter.diagnoses.values_list("pk", flat=True)) == [keep.pk]


def test_sync_related_empty_items_deletes_all_existing(doctor_user):
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)
    encounter.diagnoses.create(description="Gone", is_primary=False)

    _sync_related(
        encounter.diagnoses,
        [],
        is_valid=lambda item: bool(item.get("description")),
        build_fields=lambda item: {
            "description": item["description"],
            "is_primary": item.get("is_primary", False),
        },
    )

    assert encounter.diagnoses.count() == 0


def test_sync_related_invalid_items_are_skipped_entirely(doctor_user):
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)
    keep = encounter.diagnoses.create(description="Keep", is_primary=False)

    _sync_related(
        encounter.diagnoses,
        [{"description": ""}],  # invalid: empty description
        is_valid=lambda item: bool(item.get("description")),
        build_fields=lambda item: {
            "description": item["description"],
            "is_primary": item.get("is_primary", False),
        },
    )

    # Invalid item is skipped; it does not count toward keep_ids, but since
    # it was never processed the existing row is *not* deleted by it either
    # -- only rows omitted by *valid* resubmission are pruned. Here nothing
    # valid was submitted, so keep_ids is empty and the existing row is
    # deleted (same as the empty-items case).
    assert encounter.diagnoses.count() == 0
    assert keep.pk not in encounter.diagnoses.values_list("pk", flat=True)


def test_sync_related_id_from_another_encounter_is_not_hijacked(doctor_user):
    """An id belonging to another encounter's diagnosis must not be updated
    through a differently-scoped manager -- it should be treated as a create
    instead, since manager.filter(pk=item_id) is scoped to the owning
    encounter."""
    patient = _make_patient()
    encounter_a = _make_encounter(patient, doctor_user)
    encounter_b = _make_encounter(patient, doctor_user)
    foreign = encounter_a.diagnoses.create(description="Belongs to A", is_primary=False)

    _sync_related(
        encounter_b.diagnoses,
        [{"id": foreign.pk, "description": "New for B", "is_primary": False}],
        is_valid=lambda item: bool(item.get("description")),
        build_fields=lambda item: {
            "description": item["description"],
            "is_primary": item.get("is_primary", False),
        },
    )

    foreign.refresh_from_db()
    assert foreign.description == "Belongs to A"  # untouched
    assert encounter_b.diagnoses.count() == 1
    assert encounter_b.diagnoses.first().description == "New for B"


# ---------------------------------------------------------------------------
# Search filters: masked-role behavior differs per filter (pinned here so B1
# can be verified byte-identical against this behavior)
# ---------------------------------------------------------------------------


def test_patient_search_filter_masked_role_bypasses_search_entirely(it_user):
    match = _make_patient(first_name="Ana", cedula="00112345671")
    other = _make_patient(first_name="Luis", last_name="Perez", cedula="00112345672")

    request = _search_request(it_user, "Ana")
    qs = PatientSearchFilter().filter_queryset(request, Patient.objects.all(), None)

    assert set(qs.values_list("id", flat=True)) == {match.id, other.id}


def test_patient_search_filter_unmasked_role_filters_by_name(receptionist_user):
    match = _make_patient(first_name="Ana", cedula="00112345671")
    _make_patient(first_name="Luis", last_name="Perez", cedula="00112345672")

    request = _search_request(receptionist_user, "Ana")
    qs = PatientSearchFilter().filter_queryset(request, Patient.objects.all(), None)

    assert list(qs.values_list("id", flat=True)) == [match.id]


def test_encounter_search_filter_masked_role_restricted_to_doctor_code_and_number(
    it_user, doctor_user
):
    doctor = _make_doctor(doctor_user)
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user, doctor=doctor)

    # Masked role: patient-name term finds nothing (name search withheld).
    request = _search_request(it_user, patient.first_name)
    qs = EncounterSearchFilter().filter_queryset(request, Encounter.objects.all(), None)
    assert qs.count() == 0

    # Masked role: doctor-code term still works.
    request = _search_request(it_user, doctor.code)
    qs = EncounterSearchFilter().filter_queryset(request, Encounter.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [encounter.id]


def test_encounter_search_filter_masked_role_gets_no_digit_search(it_user, doctor_user):
    patient = _make_patient(cedula="00112345678")
    _make_encounter(patient, doctor_user)

    request = _search_request(it_user, "00112345678")
    qs = EncounterSearchFilter().filter_queryset(request, Encounter.objects.all(), None)
    assert qs.count() == 0


def test_encounter_search_filter_unmasked_role_matches_patient_name_and_digits(
    receptionist_user, doctor_user
):
    patient = _make_patient(first_name="Ana", cedula="00112345678")
    encounter = _make_encounter(patient, doctor_user)

    request = _search_request(receptionist_user, "Ana")
    qs = EncounterSearchFilter().filter_queryset(request, Encounter.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [encounter.id]

    request = _search_request(receptionist_user, "00112345678")
    qs = EncounterSearchFilter().filter_queryset(request, Encounter.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [encounter.id]


def test_record_search_filter_masked_role_matches_name_but_not_digits(it_user, doctor_user):
    """RecordSearchFilter has no free-text field to search anymore (title
    moved to RecordEntry-level content, which isn't searched here), so name
    matching is unconditional (always_lookups) rather than gated behind an
    unmasked role -- moot in production since IT/CENTER_MANAGER can't reach
    /api/medical-records/ at all (IsAdminDoctorOrNurse), but this filter is
    tested here in isolation from that permission layer."""
    patient = _make_patient(first_name="Ana", cedula="00112345678")
    record = MedicalRecord.objects.create(patient=patient, created_by=doctor_user)

    request = _search_request(it_user, "Ana")
    qs = RecordSearchFilter().filter_queryset(request, MedicalRecord.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [record.id]

    # Digit-based matching stays gated to unmasked roles.
    request = _search_request(it_user, "00112345678")
    qs = RecordSearchFilter().filter_queryset(request, MedicalRecord.objects.all(), None)
    assert qs.count() == 0


def test_record_search_filter_unmasked_role_matches_patient_name_and_digits(
    receptionist_user, doctor_user
):
    patient = _make_patient(first_name="Ana", cedula="00112345678")
    record = MedicalRecord.objects.create(patient=patient, created_by=doctor_user)

    request = _search_request(receptionist_user, "Ana")
    qs = RecordSearchFilter().filter_queryset(request, MedicalRecord.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [record.id]

    request = _search_request(receptionist_user, "00112345678")
    qs = RecordSearchFilter().filter_queryset(request, MedicalRecord.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [record.id]


def test_patient_search_filter_multiple_terms_are_and_ed(receptionist_user):
    match = _make_patient(first_name="Ana", last_name="Perez", cedula="00112345671")
    _make_patient(first_name="Ana", last_name="Lopez", cedula="00112345672")

    request = _search_request(receptionist_user, "Ana Perez")
    qs = PatientSearchFilter().filter_queryset(request, Patient.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [match.id]


def test_patient_search_filter_guardian_cedula_matches(receptionist_user):
    from apps.patients.models import PatientGuardian

    guardian_cedula = "00198765432"
    minor = _make_patient(first_name="Kid", cedula="", has_guardian=True)
    PatientGuardian.objects.create(
        patient=minor, first_name="Parent", last_name="One", cedula=guardian_cedula,
    )

    request = _search_request(receptionist_user, guardian_cedula)
    qs = PatientSearchFilter().filter_queryset(request, Patient.objects.all(), None)
    assert list(qs.values_list("id", flat=True)) == [minor.id]


def test_encounter_search_filter_does_not_match_guardian_cedula(receptionist_user, doctor_user):
    """EncounterSearchFilter's digit lookup deliberately omits
    include_guardian -- confirms the one documented behavioral fork between
    PatientSearchFilter and EncounterSearchFilter."""
    from apps.patients.models import PatientGuardian

    guardian_cedula = "00198765432"
    minor = _make_patient(first_name="Kid", cedula="", has_guardian=True)
    PatientGuardian.objects.create(
        patient=minor, first_name="Parent", last_name="One", cedula=guardian_cedula,
    )
    _make_encounter(minor, doctor_user)

    request = _search_request(receptionist_user, guardian_cedula)
    qs = EncounterSearchFilter().filter_queryset(request, Encounter.objects.all(), None)
    assert qs.count() == 0


# ---------------------------------------------------------------------------
# Write-side scoping predicates (B2: can_write_center, is_own_doctor_relation,
# program_belongs_to_ars)
# ---------------------------------------------------------------------------


def test_can_write_center_non_doctor_always_true(admin_user, receptionist_user):
    center = _make_center(code="C-CWC1")
    assert can_write_center(admin_user, center) is True
    assert can_write_center(receptionist_user, center) is True


def test_can_write_center_none_center_always_true(doctor_user):
    assert can_write_center(doctor_user, None) is True


def test_can_write_center_doctor_approved(doctor_user):
    doctor = _make_doctor(doctor_user)
    center = _make_center(code="C-CWC2")
    DoctorCenterBinding.objects.create(doctor=doctor, center=center, approved=True)
    assert can_write_center(doctor_user, center) is True


def test_can_write_center_doctor_not_approved(doctor_user):
    doctor = _make_doctor(doctor_user)
    center = _make_center(code="C-CWC3")
    DoctorCenterBinding.objects.create(doctor=doctor, center=center, approved=False)
    assert can_write_center(doctor_user, center) is False


def test_can_write_center_doctor_no_binding(doctor_user):
    center = _make_center(code="C-CWC4")
    assert can_write_center(doctor_user, center) is False


def test_is_own_doctor_relation_non_doctor_always_true(admin_user, doctor_user):
    other_doctor = _make_doctor(doctor_user)
    assert is_own_doctor_relation(admin_user, other_doctor) is True


def test_is_own_doctor_relation_doctor_own_profile(doctor_user):
    own = _make_doctor(doctor_user)
    assert is_own_doctor_relation(doctor_user, own) is True


def test_is_own_doctor_relation_doctor_foreign_profile(doctor_user, admin_user):
    _make_doctor(doctor_user)
    foreign = DoctorProfile.objects.create(
        user=admin_user, license_number="LIC-FOREIGN", contact_phone="8095550001"
    )
    assert is_own_doctor_relation(doctor_user, foreign) is False


def test_is_own_doctor_relation_doctor_without_profile(doctor_user, admin_user):
    foreign = DoctorProfile.objects.create(
        user=admin_user, license_number="LIC-NOPROFILE", contact_phone="8095550002"
    )
    assert is_own_doctor_relation(doctor_user, foreign) is False


def test_program_belongs_to_ars_none_ars_or_program_always_true(db):
    from apps.ars.models import ARS, ARSProgram

    ars = ARS.objects.create(ars_id="A1", name="Test ARS")
    program = ARSProgram.objects.create(ars=ars, name="Basic")
    assert program_belongs_to_ars(None, program) is True
    assert program_belongs_to_ars(ars, None) is True
    assert program_belongs_to_ars(None, None) is True


def test_program_belongs_to_ars_matching(db):
    from apps.ars.models import ARS, ARSProgram

    ars = ARS.objects.create(ars_id="A2", name="Matching ARS")
    program = ARSProgram.objects.create(ars=ars, name="Plus")
    assert program_belongs_to_ars(ars, program) is True


def test_program_belongs_to_ars_mismatched(db):
    from apps.ars.models import ARS, ARSProgram

    ars_a = ARS.objects.create(ars_id="A3", name="ARS A")
    ars_b = ARS.objects.create(ars_id="A4", name="ARS B")
    program = ARSProgram.objects.create(ars=ars_b, name="Plus")
    assert program_belongs_to_ars(ars_a, program) is False


# ---------------------------------------------------------------------------
# is_owner_doctor (B4)
# ---------------------------------------------------------------------------


def test_is_owner_doctor_non_doctor_always_true(admin_user, doctor_user):
    doctor = _make_doctor(doctor_user)
    patient = _make_patient()
    appointment = _make_encounter(patient, doctor_user, doctor=doctor)
    assert is_owner_doctor(admin_user, appointment) is True


def test_is_owner_doctor_owning_doctor_true(doctor_user):
    doctor = _make_doctor(doctor_user)
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user, doctor=doctor)
    assert is_owner_doctor(doctor_user, encounter) is True


def test_is_owner_doctor_foreign_doctor_false(doctor_user, admin_user):
    other_user_doctor = _make_doctor(doctor_user)
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user, doctor=other_user_doctor)

    from apps.accounts.models import User

    foreign_user = User.objects.create_user(
        username="foreign_doctor", password="pass12345", role=User.Role.DOCTOR
    )
    assert is_owner_doctor(foreign_user, encounter) is False


# ---------------------------------------------------------------------------
# Encounter.has_completed_service / is_locked_for_edit (B4)
# ---------------------------------------------------------------------------


def test_encounter_not_locked_when_draft_and_no_completed_service(doctor_user):
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user)
    assert encounter.has_completed_service() is False
    assert encounter.is_locked_for_edit() is False


@pytest.mark.parametrize("status", ["COMPLETED", "CANCELLED"])
def test_encounter_locked_when_terminal_status(doctor_user, status):
    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user, status=status)
    assert encounter.is_locked_for_edit() is True


def test_encounter_locked_when_has_completed_service(doctor_user):
    from apps.services.models import Service

    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user, status="ACTIVE")
    service = Service.objects.create(
        simon="100001", name="Lab test", type=encounter.service_type, co_pago=0, privado=0
    )
    encounter.services.create(service=service, status="COMPLETED")

    assert encounter.has_completed_service() is True
    assert encounter.is_locked_for_edit() is True


def test_encounter_not_locked_when_service_pending(doctor_user):
    from apps.services.models import Service

    patient = _make_patient()
    encounter = _make_encounter(patient, doctor_user, status="ACTIVE")
    service = Service.objects.create(
        simon="100002", name="Lab test 2", type=encounter.service_type, co_pago=0, privado=0
    )
    encounter.services.create(service=service, status="PENDING")

    assert encounter.has_completed_service() is False
    assert encounter.is_locked_for_edit() is False
