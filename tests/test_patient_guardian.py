"""Guardian/Parent info for minor patients (feature/guardian-info-and-default-center).

Guardian first/last name/cedula/phone are required when the patient is a
minor (age < 18) and the "Guardian/Parent" checkbox (`has_guardian`,
default True) is checked. Guardian NSS mirrors the patient's own NSS: format
validated when present, never required. Guardian identifiers deliberately
have no uniqueness constraint -- siblings can share the same guardian.
"""

from apps.centers.models import MedicalCenter
from apps.patients.models import Patient

MASK = "••••"


def _payload(**overrides):
    data = {
        "first_name": "Kid",
        "last_name": "Doe",
        "birth_date": "2015-01-01",  # minor as of any run this decade
        "gender": "MALE",
        "phone": "8095550100",
        "cedula": "01098765432",
    }
    data.update(overrides)
    return data


def _guardian_payload(**overrides):
    data = {
        "guardian_first_name": "Maria",
        "guardian_last_name": "Doe",
        "guardian_cedula": "00112345678",
        "guardian_phone": "8095550199",
    }
    data.update(overrides)
    return data


def test_guardian_required_when_minor_checkbox_default(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post("/api/patients/", _payload(), format="json")
    assert res.status_code == 400, res.data
    for field in ("guardian_first_name", "guardian_last_name", "guardian_cedula", "guardian_phone"):
        assert field in res.data


def test_guardian_not_required_when_checkbox_unchecked(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/", _payload(has_guardian=False), format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["has_guardian"] is False


def test_guardian_not_required_for_adult(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _payload(birth_date="1990-05-12", cedula="01098765499"),
        format="json",
    )
    assert res.status_code == 201, res.data


def test_guardian_valid_data_persists_and_round_trips(auth_client, receptionist_user):
    payload = {**_payload(cedula="01098765401"), **_guardian_payload()}
    res = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert res.status_code == 201, res.data
    assert res.data["guardian_first_name"] == "Maria"
    assert res.data["guardian_cedula"] == "00112345678"

    patient = Patient.objects.get(pk=res.data["id"])
    assert patient.guardian_first_name == "Maria"
    assert patient.guardian_cedula == "00112345678"

    detail = auth_client(receptionist_user).get(f"/api/patients/{patient.id}/")
    assert detail.data["guardian_last_name"] == "Doe"
    assert detail.data["guardian_phone"] == "8095550199"


def test_guardian_cedula_format_validation(auth_client, receptionist_user):
    payload = {**_payload(cedula="01098765402"), **_guardian_payload(guardian_cedula="123")}
    res = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "guardian_cedula" in res.data


def test_guardian_phone_format_validation(auth_client, receptionist_user):
    payload = {**_payload(cedula="01098765403"), **_guardian_payload(guardian_phone="123")}
    res = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "guardian_phone" in res.data


def test_guardian_nss_optional_but_validated_when_present(auth_client, receptionist_user):
    ok_payload = {**_payload(cedula="01098765404"), **_guardian_payload(guardian_nss="")}
    ok_res = auth_client(receptionist_user).post("/api/patients/", ok_payload, format="json")
    assert ok_res.status_code == 201, ok_res.data

    bad_payload = {**_payload(cedula="01098765405"), **_guardian_payload(guardian_nss="abc")}
    bad_res = auth_client(receptionist_user).post("/api/patients/", bad_payload, format="json")
    assert bad_res.status_code == 400, bad_res.data
    assert "guardian_nss" in bad_res.data


def test_patch_unrelated_field_does_not_relock_legacy_minor(auth_client, receptionist_user):
    """Regression test for the PATCH-lockout fix in PatientSerializer.validate().

    A minor created before this feature existed (or seeded directly via the
    ORM, like seed_demo_data.py does) has has_guardian=True by default and
    blank guardian fields. Patching an unrelated field must not re-trigger
    the guardian-required check against that blank fallback.
    """
    patient = Patient.objects.create(
        first_name="Legacy",
        last_name="Minor",
        birth_date="2015-01-01",
        gender="MALE",
        cedula="01098765406",
    )
    assert patient.has_guardian is True
    assert patient.guardian_first_name == ""

    res = auth_client(receptionist_user).patch(
        f"/api/patients/{patient.id}/", {"phone": "8095551234"}, format="json"
    )
    assert res.status_code == 200, res.data


def test_patch_touching_guardian_field_still_enforces(auth_client, receptionist_user):
    patient = Patient.objects.create(
        first_name="Legacy2",
        last_name="Minor",
        birth_date="2015-01-01",
        gender="MALE",
        cedula="01098765409",
    )
    res = auth_client(receptionist_user).patch(
        f"/api/patients/{patient.id}/",
        {"guardian_first_name": "Only One Field"},
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "guardian_last_name" in res.data


def test_guardian_fields_masked_for_it(auth_client, it_user, receptionist_user):
    payload = {**_payload(cedula="01098765407"), **_guardian_payload()}
    created = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert created.status_code == 201, created.data

    res = auth_client(it_user).get(f"/api/patients/{created.data['id']}/")
    assert res.status_code == 200, res.data
    assert MASK in res.data["guardian_first_name"]
    assert MASK in res.data["guardian_last_name"]
    assert MASK in res.data["guardian_cedula"]
    assert MASK in res.data["guardian_phone"]
    assert res.data["age"] is None


def test_guardian_fields_masked_for_center_manager(auth_client, center_manager_user, receptionist_user):
    payload = {**_payload(cedula="01098765410"), **_guardian_payload()}
    created = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert created.status_code == 201, created.data

    res = auth_client(center_manager_user).get(f"/api/patients/{created.data['id']}/")
    assert res.status_code == 200, res.data
    assert MASK in res.data["guardian_cedula"]


def test_adult_cedula_still_required(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _payload(birth_date="1990-05-12", cedula=""),
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data


def test_minor_without_guardian_requires_own_cedula(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        _payload(has_guardian=False, cedula=""),
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "cedula" in res.data


def test_minor_with_guardian_cedula_not_required(auth_client, receptionist_user):
    payload = {**_payload(cedula=""), **_guardian_payload()}
    res = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert res.status_code == 201, res.data
    assert res.data["cedula"] == ""


def test_minor_with_guardian_blank_cedula_and_blank_guardian_cedula_rejected(
    auth_client, receptionist_user
):
    payload = {
        **_payload(cedula=""),
        **_guardian_payload(guardian_cedula=""),
    }
    res = auth_client(receptionist_user).post("/api/patients/", payload, format="json")
    assert res.status_code == 400, res.data
    assert "guardian_cedula" in res.data
    assert "cedula" not in res.data


def test_patch_unrelated_field_does_not_relock_legacy_minor_blank_cedula(
    auth_client, receptionist_user
):
    """Same PATCH-lockout regression as
    test_patch_unrelated_field_does_not_relock_legacy_minor, but for a legacy
    minor with BOTH blank guardian fields AND blank cedula -- the worst case
    the new cedula-requiredness logic could newly break.
    """
    patient = Patient.objects.create(
        first_name="Legacy3",
        last_name="Minor",
        birth_date="2015-01-01",
        gender="MALE",
        cedula="",
    )
    assert patient.has_guardian is True
    assert patient.cedula == ""

    res = auth_client(receptionist_user).patch(
        f"/api/patients/{patient.id}/", {"phone": "8095551234"}, format="json"
    )
    assert res.status_code == 200, res.data


def test_center_code_in_output(auth_client, receptionist_user):
    center = MedicalCenter.objects.create(
        name="Test Center", code="TC01", address="1 Test St", phone="8095550001"
    )
    res = auth_client(receptionist_user).post(
        "/api/patients/",
        {**_payload(birth_date="1990-01-01", cedula="01098765408"), "center": center.id},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["center_code"] == "TC01"


# ---------------------------------------------------------------------------
# Guardian cedula search (PatientSearchFilter, apps/patients/filters.py):
# front-desk staff can find a minor by their guardian's cedula, the only ID
# they may have on hand. Scoped to /api/patients/ (and everything that reuses
# it, e.g. the Encounters admission form's patient picker) -- the Encounters
# list's own search bar stays patient-cedula-only by separate design.
# ---------------------------------------------------------------------------


def test_search_by_guardian_cedula_finds_minor(auth_client, receptionist_user):
    auth_client(receptionist_user).post(
        "/api/patients/", {**_payload(), **_guardian_payload()}, format="json"
    )
    res = auth_client(receptionist_user).get("/api/patients/?search=00112345678")
    assert res.data["count"] == 1
    assert res.data["results"][0]["first_name"] == "Kid"


def test_search_by_guardian_cedula_returns_all_siblings(auth_client, receptionist_user):
    auth_client(receptionist_user).post(
        "/api/patients/",
        {**_payload(cedula="01098765401"), **_guardian_payload()},
        format="json",
    )
    auth_client(receptionist_user).post(
        "/api/patients/",
        {
            **_payload(first_name="Sibling", cedula="01098765402"),
            **_guardian_payload(),
        },
        format="json",
    )
    res = auth_client(receptionist_user).get("/api/patients/?search=00112345678")
    assert res.data["count"] == 2


def test_encounters_search_does_not_match_guardian_cedula(
    auth_client, admin_user, receptionist_user
):
    """The Encounters list's own search bar (EncounterSearchFilter) was
    deliberately scoped to the patient's own cedula only -- confirms adding
    guardian-cedula search to PatientSearchFilter didn't leak into it."""
    from apps.doctors.models import DoctorProfile
    from apps.encounters.models import Encounter
    from apps.services.models import ServiceType

    create = auth_client(receptionist_user).post(
        "/api/patients/", {**_payload(), **_guardian_payload()}, format="json"
    )
    patient = Patient.objects.get(pk=create.data["id"])
    doctor = DoctorProfile.objects.create(
        user=admin_user, license_number="LIC-GCS", contact_phone="1",
    )
    service_type = ServiceType.objects.get_or_create(name="Consulta General")[0]
    Encounter.objects.create(
        service_type=service_type, patient=patient, doctor=doctor, created_by=admin_user,
    )

    res = auth_client(admin_user).get("/api/encounters/?search=00112345678")
    assert res.data["count"] == 0


def test_masked_role_search_ignores_guardian_cedula_term(
    auth_client, receptionist_user, it_user
):
    """Masked roles (IT/CENTER_MANAGER) get PatientSearchFilter's existing
    "ignore the search term entirely" bypass (a PII-existence-oracle guard
    that predates this change) -- confirms the new guardian-cedula matching
    doesn't carve out an exception to it. A second, non-matching patient
    proves the search term was actually ignored rather than coincidentally
    matching everything in an otherwise-empty test DB."""
    auth_client(receptionist_user).post(
        "/api/patients/", {**_payload(), **_guardian_payload()}, format="json"
    )
    auth_client(receptionist_user).post(
        "/api/patients/",
        _payload(first_name="Other", birth_date="1990-01-01", cedula="01098765403"),
        format="json",
    )
    res = auth_client(it_user).get("/api/patients/?search=00112345678")
    assert res.data["count"] == 2
