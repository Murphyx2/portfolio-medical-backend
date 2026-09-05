"""RecordEntry: draft/completed lifecycle, MedicalRecord's last-* cache
recompute, vitals validation, and AP snapshotting -- the core of the
Expedientes Médicos refactor (Requirements/EXPEDIENTES_MEDICOS_AI_SPEC.md).
"""

from decimal import Decimal

from apps.patients.models import Patient
from apps.records.models import (
    APCategory,
    APType,
    MedicalRecord,
    RecordEntry,
    RecordFamilyCondition,
    RecordPersonalCondition,
)


def _patient(**overrides):
    data = {"first_name": "Jane", "last_name": "Doe", "gender": "FEMALE", "cedula": "00112345678"}
    data.update(overrides)
    return Patient.objects.create(**data)


def _record(patient, user):
    return MedicalRecord.objects.create(patient=patient, created_by=user)


# ---------------------------------------------------------------------------
# Draft upsert idempotency (spec §11: "exactly one draft per expediente per user")
# ---------------------------------------------------------------------------


def test_draft_upsert_is_idempotent_per_author(auth_client, doctor_user, receptionist_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    client = auth_client(doctor_user)

    res = client.post("/api/record-entries/draft/", {"record": record.id, "dx": "First"}, format="json")
    assert res.status_code == 200, res.data
    entry_id = res.data["id"]
    assert RecordEntry.objects.filter(record=record, status="DRAFT").count() == 1

    res = client.post("/api/record-entries/draft/", {"record": record.id, "dx": "Updated"}, format="json")
    assert res.status_code == 200, res.data
    assert res.data["id"] == entry_id
    assert res.data["dx"] == "Updated"
    assert RecordEntry.objects.filter(record=record, status="DRAFT").count() == 1


def test_two_authors_each_get_their_own_draft(auth_client, doctor_user, nurse_user):
    patient = _patient()
    record = _record(patient, doctor_user)

    auth_client(doctor_user).post("/api/record-entries/draft/", {"record": record.id, "dx": "Doctor's"}, format="json")
    auth_client(nurse_user).post("/api/record-entries/draft/", {"record": record.id, "dx": "Nurse's"}, format="json")

    assert RecordEntry.objects.filter(record=record, status="DRAFT").count() == 2


def test_draft_never_touches_last_visit_or_measurements(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/draft/",
        {"record": record.id, "ta_systolic": 120, "ta_diastolic": 80, "dx": "Draft only"},
        format="json",
    )
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert record.last_visit_at is None
    assert record.last_ta_systolic is None


def test_draft_cannot_be_edited_by_a_different_author(auth_client, doctor_user, nurse_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Doctor's draft")

    res = auth_client(nurse_user).patch(
        f"/api/record-entries/{draft.id}/", {"dx": "Hijacked"}, format="json"
    )
    assert res.status_code == 403, res.data


def test_draft_deletable_only_by_its_own_author(auth_client, doctor_user, nurse_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Mine")

    res = auth_client(nurse_user).delete(f"/api/record-entries/{draft.id}/")
    assert res.status_code == 403, res.data

    res = auth_client(doctor_user).delete(f"/api/record-entries/{draft.id}/")
    assert res.status_code == 204, res.data


# ---------------------------------------------------------------------------
# complete(): no-changes guard, last-* recompute rules
# ---------------------------------------------------------------------------


def test_complete_blocked_when_every_clinical_field_empty(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT")

    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 400, res.data
    assert res.data.get("code") == "NO_CHANGES"
    draft.refresh_from_db()
    assert draft.status == "DRAFT"


def test_complete_with_only_dx_updates_last_visit_but_not_vitals(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Migraine")

    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert record.last_visit_at is not None
    assert record.last_ta_systolic is None


def test_complete_sets_last_ta_fc_fr_glucose(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT")

    res = auth_client(doctor_user).post(
        f"/api/record-entries/{draft.id}/complete/",
        {"ta_systolic": 120, "ta_diastolic": 80, "fc": 72, "fr": 16, "glucose": 95},
        format="json",
    )
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert record.last_ta_systolic == 120
    assert record.last_ta_diastolic == 80
    assert record.last_fc == 72
    assert record.last_fr == 16
    assert record.last_glucose == 95
    assert record.last_visit_at is not None


def test_clearing_a_field_before_complete_does_not_update_last_measurement(auth_client, doctor_user):
    """Spec §11: 'Type then clear before Guardar -- does not update last
    measurement or last visit' (for that field)."""
    patient = _patient()
    record = _record(patient, doctor_user)
    # First entry establishes a baseline FC.
    first = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", fc=80)
    auth_client(doctor_user).post(f"/api/record-entries/{first.id}/complete/", {}, format="json")
    record.refresh_from_db()
    assert record.last_fc == 80

    # Second entry: FC left blank, but dx present so the save isn't a no-op.
    second = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Follow-up")
    res = auth_client(doctor_user).post(f"/api/record-entries/{second.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert record.last_fc == 80  # untouched, not cleared


def test_imc_computed_from_weight_and_height_on_same_entry(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT")

    res = auth_client(doctor_user).post(
        f"/api/record-entries/{draft.id}/complete/",
        {"weight_lb": "154", "height_cm": "170"},
        format="json",
    )
    assert res.status_code == 200, res.data
    # 154 lb = 69.853 kg; 1.70 m; imc = 69.853 / 2.89 = 24.17
    assert Decimal(res.data["imc"]) == Decimal("24.17")
    record.refresh_from_db()
    assert record.last_imc == Decimal("24.17")


def test_imc_recomputed_using_prior_measurement_on_the_other_side(auth_client, doctor_user):
    """Weight recorded today, height already on file from a prior visit --
    IMC still computes by combining the new value with the cached one."""
    patient = _patient()
    record = _record(patient, doctor_user)
    first = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", height_cm="170")
    auth_client(doctor_user).post(f"/api/record-entries/{first.id}/complete/", {}, format="json")

    second = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT")
    res = auth_client(doctor_user).post(
        f"/api/record-entries/{second.id}/complete/", {"weight_lb": "154"}, format="json"
    )
    assert res.status_code == 200, res.data
    assert Decimal(res.data["imc"]) == Decimal("24.17")


# ---------------------------------------------------------------------------
# "Editar última entrada": author/timestamp preserved on resave, only latest editable
# ---------------------------------------------------------------------------


def test_editing_last_completed_entry_preserves_original_author_and_completed_at(
    auth_client, doctor_user, admin_user
):
    patient = _patient()
    record = _record(patient, doctor_user)
    entry = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Original")
    auth_client(doctor_user).post(f"/api/record-entries/{entry.id}/complete/", {}, format="json")
    entry.refresh_from_db()
    original_author_id = entry.author_id
    original_completed_at = entry.completed_at

    res = auth_client(admin_user).post(
        f"/api/record-entries/{entry.id}/complete/", {"dx": "Amended"}, format="json"
    )
    assert res.status_code == 200, res.data
    entry.refresh_from_db()
    assert entry.author_id == original_author_id
    assert entry.completed_at == original_completed_at
    assert entry.dx == "Amended"


def test_older_completed_entry_is_read_only(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    older = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Old")
    auth_client(doctor_user).post(f"/api/record-entries/{older.id}/complete/", {}, format="json")

    newer = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="New")
    auth_client(doctor_user).post(f"/api/record-entries/{newer.id}/complete/", {}, format="json")

    res = auth_client(doctor_user).post(
        f"/api/record-entries/{older.id}/complete/", {"dx": "Trying to edit old"}, format="json"
    )
    assert res.status_code == 403, res.data


def test_completed_entry_is_never_deletable(auth_client, admin_user, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    entry = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Done")
    auth_client(doctor_user).post(f"/api/record-entries/{entry.id}/complete/", {}, format="json")

    res = auth_client(admin_user).delete(f"/api/record-entries/{entry.id}/")
    assert res.status_code == 403, res.data


# ---------------------------------------------------------------------------
# Vitals validation
# ---------------------------------------------------------------------------


def test_ta_requires_both_parts_or_neither(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/", {"record": record.id, "ta_systolic": 120}, format="json"
    )
    assert res.status_code == 400, res.data


def test_ta_out_of_range_rejected(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/",
        {"record": record.id, "ta_systolic": 500, "ta_diastolic": 80},
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "ta_systolic" in res.data


def test_glucose_out_of_range_rejected(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/", {"record": record.id, "glucose": 5000}, format="json"
    )
    assert res.status_code == 400, res.data
    assert "glucose" in res.data


# ---------------------------------------------------------------------------
# Role matrix
# ---------------------------------------------------------------------------


def test_receptionist_cannot_read_or_write_record_entries(auth_client, receptionist_user, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    client = auth_client(receptionist_user)
    assert client.get("/api/record-entries/").status_code == 403
    assert client.post("/api/record-entries/", {"record": record.id}, format="json").status_code == 403


# ---------------------------------------------------------------------------
# AP snapshot: frozen at complete() time
# ---------------------------------------------------------------------------


def test_personal_ap_snapshot_frozen_at_complete_time(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    category = APCategory.objects.create(name="Cardio Test")
    ap_type = APType.objects.create(category=category, name="HTA Test")
    RecordPersonalCondition.objects.create(record=record, ap_type=ap_type)
    RecordPersonalCondition.objects.create(record=record, custom_label="Cirugía de rodilla", is_custom=True)

    entry = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Checkup")
    res = auth_client(doctor_user).post(f"/api/record-entries/{entry.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data
    snapshot = res.data["personal_ap_snapshot"]
    assert len(snapshot) == 2
    labels = {item["label"] for item in snapshot}
    assert labels == {"HTA Test", "Cirugía de rodilla"}

    # Removing the living condition afterward must not rewrite the snapshot.
    RecordPersonalCondition.objects.filter(ap_type=ap_type).delete()
    entry.refresh_from_db()
    assert len(entry.personal_ap_snapshot) == 2


def test_family_ap_snapshot_includes_relationship(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    category = APCategory.objects.create(name="Endocrino Test")
    ap_type = APType.objects.create(category=category, name="Diabetes Test")
    RecordFamilyCondition.objects.create(
        record=record, relationship="MADRE", ap_type=ap_type,
    )

    entry = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT", dx="Checkup")
    res = auth_client(doctor_user).post(f"/api/record-entries/{entry.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data
    snapshot = res.data["family_ap_snapshot"]
    assert len(snapshot) == 1
    assert snapshot[0]["relationship"] == "MADRE"
    assert snapshot[0]["label"] == "Diabetes Test"


# ---------------------------------------------------------------------------
# RecordPersonalCondition / RecordFamilyCondition validation
# ---------------------------------------------------------------------------


def test_personal_condition_requires_exactly_one_of_ap_type_or_custom_label(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    client = auth_client(doctor_user)

    res = client.post("/api/personal-conditions/", {"record": record.id}, format="json")
    assert res.status_code == 400, res.data

    category = APCategory.objects.create(name="Both Test")
    ap_type = APType.objects.create(category=category, name="Both Type")
    res = client.post(
        "/api/personal-conditions/",
        {"record": record.id, "ap_type": ap_type.id, "custom_label": "Also custom"},
        format="json",
    )
    assert res.status_code == 400, res.data


def test_family_condition_otro_requires_relationship_other(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    category = APCategory.objects.create(name="Otro Test")
    ap_type = APType.objects.create(category=category, name="Otro AP")

    res = auth_client(doctor_user).post(
        "/api/family-conditions/",
        {"record": record.id, "relationship": "OTRO", "ap_type": ap_type.id},
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "relationship_other" in res.data

    res = auth_client(doctor_user).post(
        "/api/family-conditions/",
        {
            "record": record.id, "relationship": "OTRO", "relationship_other": "Prima",
            "ap_type": ap_type.id,
        },
        format="json",
    )
    assert res.status_code == 201, res.data


def test_nurse_can_manage_conditions_on_own_record_but_not_others(
    auth_client, nurse_user, make_user
):
    other = make_user("doctor2", "DOCTOR")
    patient = _patient()
    own_record = _record(patient, nurse_user)
    other_patient = _patient(first_name="Other", cedula="00112345679")
    other_record = _record(other_patient, other)
    category = APCategory.objects.create(name="Nurse Scope Test")
    ap_type = APType.objects.create(category=category, name="Nurse Scope Type")

    own_condition = RecordPersonalCondition.objects.create(record=own_record, ap_type=ap_type)
    other_condition = RecordPersonalCondition.objects.create(record=other_record, ap_type=ap_type)

    client = auth_client(nurse_user)
    assert client.delete(f"/api/personal-conditions/{own_condition.id}/").status_code == 204
    assert client.delete(f"/api/personal-conditions/{other_condition.id}/").status_code == 403
