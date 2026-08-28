"""Hábitos tab: has_clinical_content() gating, complete()'s habits_snapshot
recompute/clear logic, masking, and habits validation
(Requirements/Habits/HABITOS_TAB_REQUIREMENTS.md).
"""

from apps.patients.models import Patient
from apps.records.models import MedicalRecord, RecordEntry
from apps.records.serializers import RecordEntrySerializer


def _patient(**overrides):
    data = {"first_name": "Jane", "last_name": "Doe", "gender": "FEMALE", "cedula": "00112345678"}
    data.update(overrides)
    return Patient.objects.create(**data)


def _record(patient, user):
    return MedicalRecord.objects.create(patient=patient, created_by=user)


# ---------------------------------------------------------------------------
# has_clinical_content(): a habit only counts with an actual signal
# ---------------------------------------------------------------------------


def test_habits_only_status_unblocks_complete(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"tabaco": {"status": "activo"}},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data


def test_habits_only_no_registrado_still_blocked(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"tabaco": {"status": "no_registrado"}},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 400, res.data
    assert res.data.get("code") == "NO_CHANGES"


def test_diet_tags_only_unblocks_complete(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"patron_alimentario": {"tags": ["vegetariano"]}},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data


def test_empty_diet_tags_still_blocked(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"patron_alimentario": {"tags": []}},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 400, res.data


def test_named_otro_habito_unblocks_complete(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"otros": [{"name": "Bruxismo"}]},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data


def test_unnamed_otro_habito_still_blocked(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"otros": [{"name": "  "}]},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 400, res.data


def test_habits_notes_alone_unblocks_complete(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT", habits_notes="Intentó dejar en marzo.",
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data


# ---------------------------------------------------------------------------
# complete(): habits_snapshot recompute, pack-years, no_registrado clears
# ---------------------------------------------------------------------------


def test_complete_writes_habits_snapshot_status_and_date(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"tabaco": {"status": "activo"}},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert record.habits_snapshot["tabaco"]["status"] == "activo"
    assert record.habits_snapshot["tabaco"]["at"]


def test_pack_years_computed_on_complete(auth_client, doctor_user):
    """Spec's own example: 10 cig/d over 8 years -> 4.0 paq-año."""
    patient = _patient()
    record = _record(patient, doctor_user)
    draft = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"tabaco": {"status": "activo", "cantidad_dia": 10, "tiempo_anios": 8}},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{draft.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert record.habits_snapshot["tabaco"]["pack_years"] == "4.0"


def test_no_registrado_on_completed_save_clears_living_value_but_not_history(
    auth_client, doctor_user
):
    patient = _patient()
    record = _record(patient, doctor_user)

    first = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"tabaco": {"status": "activo"}},
    )
    auth_client(doctor_user).post(f"/api/record-entries/{first.id}/complete/", {}, format="json")
    record.refresh_from_db()
    assert record.habits_snapshot["tabaco"]["status"] == "activo"

    second = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"tabaco": {"status": "no_registrado"}, "alcohol": {"status": "nunca"}},
    )
    res = auth_client(doctor_user).post(f"/api/record-entries/{second.id}/complete/", {}, format="json")
    assert res.status_code == 200, res.data
    record.refresh_from_db()
    assert "tabaco" not in record.habits_snapshot

    first.refresh_from_db()
    assert first.habits["tabaco"]["status"] == "activo"  # frozen historical row untouched


def test_untouched_habit_key_leaves_living_snapshot_alone(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    first = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT",
        habits={"tabaco": {"status": "activo"}},
    )
    auth_client(doctor_user).post(f"/api/record-entries/{first.id}/complete/", {}, format="json")

    second = RecordEntry.objects.create(
        record=record, author=doctor_user, status="DRAFT", dx="Unrelated follow-up",
    )
    auth_client(doctor_user).post(f"/api/record-entries/{second.id}/complete/", {}, format="json")
    record.refresh_from_db()
    assert record.habits_snapshot["tabaco"]["status"] == "activo"


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


def _serialize_as(entry, user, rf):
    request = rf.get("/")
    request.user = user
    return RecordEntrySerializer(entry, context={"request": request}).data


def test_it_role_sees_masked_habits_and_habits_notes(doctor_user, it_user, rf):
    patient = _patient()
    record = _record(patient, doctor_user)
    entry = RecordEntry.objects.create(
        record=record, author=doctor_user, status="COMPLETED",
        habits={"tabaco": {"status": "activo"}}, habits_notes="Detalle sensible",
    )
    data = _serialize_as(entry, it_user, rf)
    assert data["habits"] is None
    assert data["habits_notes"] != "Detalle sensible"


def test_doctor_role_sees_full_habits(doctor_user, rf):
    patient = _patient()
    record = _record(patient, doctor_user)
    entry = RecordEntry.objects.create(
        record=record, author=doctor_user, status="COMPLETED",
        habits={"tabaco": {"status": "activo"}}, habits_notes="Detalle clínico",
    )
    data = _serialize_as(entry, doctor_user, rf)
    assert data["habits"]["tabaco"]["status"] == "activo"
    assert data["habits_notes"] == "Detalle clínico"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_habit_key_rejected(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/draft/",
        {"record": record.id, "habits": {"not_a_real_habit": {"status": "activo"}}},
        format="json",
    )
    assert res.status_code == 400, res.data


def test_invalid_status_enum_rejected(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/draft/",
        {"record": record.id, "habits": {"tabaco": {"status": "not_a_status"}}},
        format="json",
    )
    assert res.status_code == 400, res.data


def test_otro_name_over_80_chars_rejected(auth_client, doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    res = auth_client(doctor_user).post(
        "/api/record-entries/draft/",
        {"record": record.id, "habits": {"otros": [{"name": "x" * 81}]}},
        format="json",
    )
    assert res.status_code == 400, res.data


# ---------------------------------------------------------------------------
# Migration defaults
# ---------------------------------------------------------------------------


def test_new_entry_and_record_get_empty_habit_defaults(doctor_user):
    patient = _patient()
    record = _record(patient, doctor_user)
    entry = RecordEntry.objects.create(record=record, author=doctor_user, status="DRAFT")
    assert record.habits_snapshot == {}
    assert entry.habits == {}
    assert entry.habits_notes == ""
