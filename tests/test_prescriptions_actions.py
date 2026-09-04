"""Receta business actions (emitir/anular/duplicar/pdf) + RBAC
(RECETAS_REQUIREMENTS.md §7-10). `generate_receta_pdf` is mocked throughout:
this sandbox has no system Pango/Cairo/GObject libs for WeasyPrint to
dlopen (see apps/prescriptions/pdf.py's lazy-import comment and the
backend Dockerfile, which installs them for the real container) -- these
tests exercise the emitir/anular/duplicar business logic around PDF
generation, not WeasyPrint's actual rendering."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.centers.models import MedicalCenter
from apps.doctors.models import DoctorProfile
from apps.medicines.models import Medicine
from apps.patients.models import Patient
from apps.prescriptions.models import Receta, RecetaLinea
from apps.records.models import MedicalRecord, RecordImage
from apps.services.models import Service, ServiceType


@pytest.fixture
def centro():
    return MedicalCenter.objects.create(
        name="Centro Test", code="CT1", address="Calle 1", phone="809-000-0000",
        nombre_legal="Centro Legal", nombre_corto="CT", rnc="123456789",
    )


@pytest.fixture
def medico(doctor_user):
    return DoctorProfile.objects.create(
        user=doctor_user, license_number="LIC-1", contact_phone="555-0000"
    )


@pytest.fixture
def patient():
    return Patient.objects.create(
        first_name="Jane", last_name="Doe", gender="FEMALE", birth_date="1990-01-01",
        phone="555-0100", address="123 Main St", email="jane@example.com",
    )


@pytest.fixture
def medicine():
    return Medicine.objects.create(
        generic_name="Losartan", commercial_name="Losartan LAM",
        concentracion_valor="50", concentracion_unidad="mg", via_pred="ORAL",
    )


@pytest.fixture
def borrador(centro, medico, patient, doctor_user):
    receta = Receta.objects.create(
        patient=patient, centro=centro, medico=medico, created_by=doctor_user,
        fecha=timezone.now(),
    )
    return receta


def _add_linea(receta, medicamento=None, **kwargs):
    defaults = dict(
        nombre_impreso="Old name", cantidad="30", dosis_texto="1 TAB AL DIA",
    )
    defaults.update(kwargs)
    return RecetaLinea.objects.create(receta=receta, medicamento=medicamento, **defaults)


def _lineas_payload(nombre="Losartan LAM 2", cantidad="60"):
    return [{
        "nombre_impreso": nombre, "cantidad": cantidad, "dosis_texto": "1 TAB AL DIA",
        "concentracion_valor": "50", "unidad": "mg", "via": "ORAL", "forma": "TABLETA",
        "fuera_de_catalogo": True, "dosis_json": {}, "indicacion_extra": "",
        "uso_continuo": False, "orden": 0,
    }]


@pytest.fixture
def emitida(borrador):
    """A BORRADOR pushed straight to EMITIDA (bypassing the emitir endpoint,
    since these tests target guardar_cambios/permissions, not emitir itself)
    -- carries a real stored `pdf` and a fresh `emitida_at` so the 1-hour
    window starts "now" by default."""
    _add_linea(borrador, nombre_impreso="Losartan LAM", cantidad="30")
    borrador.estado = Receta.Estado.EMITIDA
    borrador.emitida_at = timezone.now()
    borrador.pdf.save("receta_test.pdf", ContentFile(b"%PDF-fake"), save=True)
    return borrador


@pytest.fixture
def medical_record(patient, admin_user):
    return MedicalRecord.objects.create(patient=patient, created_by=admin_user)


# -- RBAC --------------------------------------------------------------


def test_nurse_cannot_create_receta(auth_client, nurse_user, centro, medico, patient):
    res = auth_client(nurse_user).post(
        "/api/recetas/",
        {"patient": patient.id, "centro": centro.id, "medico": medico.id, "fecha": timezone.now().isoformat()},
        format="json",
    )
    assert res.status_code == 403


def test_nurse_can_view_receta(auth_client, nurse_user, borrador):
    res = auth_client(nurse_user).get(f"/api/recetas/{borrador.id}/")
    assert res.status_code == 200


def test_receptionist_cannot_view_receta(auth_client, receptionist_user, borrador):
    res = auth_client(receptionist_user).get(f"/api/recetas/{borrador.id}/")
    assert res.status_code == 403


def test_doctor_can_create_receta(auth_client, doctor_user, centro, medico, patient):
    res = auth_client(doctor_user).post(
        "/api/recetas/",
        {"patient": patient.id, "centro": centro.id, "medico": medico.id, "fecha": timezone.now().isoformat()},
        format="json",
    )
    assert res.status_code == 201, res.data


# -- emitir --------------------------------------------------------------


def test_doctor_cannot_create_receta_for_another_doctor(auth_client, doctor_user, make_user, centro, patient):
    other_user = make_user(username="other-doctor", role="DOCTOR")
    other_medico = DoctorProfile.objects.create(
        user=other_user, license_number="LIC-2", contact_phone="555-0001"
    )
    res = auth_client(doctor_user).post(
        "/api/recetas/",
        {"patient": patient.id, "centro": centro.id, "medico": other_medico.id, "fecha": timezone.now().isoformat()},
        format="json",
    )
    assert res.status_code == 400
    assert "medico" in res.data


def test_admin_can_create_receta_for_any_doctor(auth_client, admin_user, medico, centro, patient):
    res = auth_client(admin_user).post(
        "/api/recetas/",
        {"patient": patient.id, "centro": centro.id, "medico": medico.id, "fecha": timezone.now().isoformat()},
        format="json",
    )
    assert res.status_code == 201, res.data


def test_emitir_requires_at_least_one_valid_linea(auth_client, doctor_user, borrador):
    res = auth_client(doctor_user).post(f"/api/recetas/{borrador.id}/emitir/")
    assert res.status_code == 400
    assert "lineas" in res.data


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_emitir_only_valid_from_borrador(mock_pdf, auth_client, doctor_user, borrador):
    _add_linea(borrador)
    borrador.estado = Receta.Estado.EMITIDA
    borrador.save()
    res = auth_client(doctor_user).post(f"/api/recetas/{borrador.id}/emitir/")
    assert res.status_code == 400


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_emitir_snapshots_live_medicine_values(mock_pdf, auth_client, doctor_user, borrador, medicine):
    linea = _add_linea(borrador, medicamento=medicine, nombre_impreso="Stale", concentracion_valor="1")
    res = auth_client(doctor_user).post(f"/api/recetas/{borrador.id}/emitir/")
    assert res.status_code == 200, res.data
    linea.refresh_from_db()
    assert linea.nombre_impreso == "Losartan LAM"
    assert linea.concentracion_valor == "50"
    assert linea.unidad == "mg"
    assert linea.via == "ORAL"
    borrador.refresh_from_db()
    assert borrador.estado == Receta.Estado.EMITIDA
    assert borrador.pdf


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_emitir_crear_cita_creates_appointment(mock_pdf, auth_client, doctor_user, borrador):
    _add_linea(borrador)
    service_type = ServiceType.objects.create(name="CONSULTA")
    service = Service.objects.create(
        simon="100001", name="Consulta general", type=service_type, co_pago=0, privado=0
    )
    proxima = (timezone.now() + timedelta(days=3)).isoformat()
    res = auth_client(doctor_user).post(
        f"/api/recetas/{borrador.id}/emitir/",
        {"crear_cita": True, "proxima_cita_at": proxima, "servicio": service.id},
        format="json",
    )
    assert res.status_code == 200, res.data
    borrador.refresh_from_db()
    assert borrador.cita_id is not None
    assert borrador.cita.status == Appointment.Status.SCHEDULED


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_emitir_crear_cita_accepts_naive_datetime_string(mock_pdf, auth_client, doctor_user, borrador):
    # Regression: the frontend sends a plain datetime-local string with no
    # timezone offset (e.g. "2026-09-16T08:22:00"), unlike .isoformat() on
    # an aware datetime which includes one -- this used to crash inside
    # check_slot_available comparing a naive proxima_cita_dt against aware
    # Appointment.date_time rows (TypeError: can't compare offset-naive and
    # offset-aware datetimes).
    _add_linea(borrador)
    service_type = ServiceType.objects.create(name="CONSULTA")
    service = Service.objects.create(
        simon="100002", name="Consulta general", type=service_type, co_pago=0, privado=0
    )
    proxima_naive = (timezone.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    res = auth_client(doctor_user).post(
        f"/api/recetas/{borrador.id}/emitir/",
        {"crear_cita": True, "proxima_cita_at": proxima_naive, "servicio": service.id},
        format="json",
    )
    assert res.status_code == 200, res.data
    borrador.refresh_from_db()
    assert borrador.cita_id is not None
    assert timezone.is_aware(borrador.cita.date_time)


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_emitir_crear_cita_conflict_blocks_everything(
    mock_pdf, auth_client, doctor_user, borrador, receptionist_user
):
    _add_linea(borrador)
    service_type = ServiceType.objects.create(name="CONSULTA")
    service = Service.objects.create(
        simon="100001", name="Consulta general", type=service_type, co_pago=0, privado=0
    )
    proxima = timezone.now() + timedelta(days=3)
    Appointment.objects.create(
        patient=borrador.patient, doctor=borrador.medico, date_time=proxima,
        created_by=receptionist_user,
    )
    res = auth_client(doctor_user).post(
        f"/api/recetas/{borrador.id}/emitir/",
        {"crear_cita": True, "proxima_cita_at": proxima.isoformat(), "servicio": service.id},
        format="json",
    )
    assert res.status_code == 400
    assert "proxima_cita_at" in res.data
    # Atomic: the receta must stay BORRADOR, no PDF, no lines mutated.
    borrador.refresh_from_db()
    assert borrador.estado == Receta.Estado.BORRADOR
    assert not borrador.pdf
    mock_pdf.assert_not_called()


# -- anular ----------------------------------------------------------------


def test_anular_by_author_succeeds(auth_client, doctor_user, borrador):
    res = auth_client(doctor_user).post(f"/api/recetas/{borrador.id}/anular/")
    assert res.status_code == 200, res.data
    borrador.refresh_from_db()
    assert borrador.estado == Receta.Estado.ANULADA


def test_anular_by_admin_succeeds(auth_client, admin_user, borrador):
    res = auth_client(admin_user).post(f"/api/recetas/{borrador.id}/anular/")
    assert res.status_code == 200, res.data


def test_anular_by_other_doctor_forbidden(auth_client, make_user, borrador):
    from apps.accounts.models import User

    other_doctor = make_user("other_doctor", User.Role.DOCTOR)
    res = auth_client(other_doctor).post(f"/api/recetas/{borrador.id}/anular/")
    assert res.status_code == 403


def test_anular_already_anulada_rejected(auth_client, doctor_user, borrador):
    borrador.estado = Receta.Estado.ANULADA
    borrador.save()
    res = auth_client(doctor_user).post(f"/api/recetas/{borrador.id}/anular/")
    assert res.status_code == 400


# -- duplicar ----------------------------------------------------------------


def test_duplicar_copies_lineas_as_new_borrador(auth_client, doctor_user, borrador):
    _add_linea(borrador, nombre_impreso="Losartan LAM", cantidad="30")
    borrador.estado = Receta.Estado.EMITIDA
    borrador.save()
    res = auth_client(doctor_user).post(f"/api/recetas/{borrador.id}/duplicar/")
    assert res.status_code == 201, res.data
    assert res.data["estado"] == Receta.Estado.BORRADOR
    assert res.data["id"] != borrador.id
    assert len(res.data["lineas"]) == 1
    assert res.data["cita"] is None
    assert not res.data["pdf"]


# -- pdf action ----------------------------------------------------------------


def test_pdf_action_404_for_borrador(auth_client, doctor_user, borrador):
    res = auth_client(doctor_user).get(f"/api/recetas/{borrador.id}/pdf/")
    assert res.status_code == 404


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_pdf_action_streams_after_emitir(mock_pdf, auth_client, doctor_user, borrador):
    _add_linea(borrador)
    auth_client(doctor_user).post(f"/api/recetas/{borrador.id}/emitir/")
    res = auth_client(doctor_user).get(f"/api/recetas/{borrador.id}/pdf/")
    assert res.status_code == 200
    assert res["Content-Type"] == "application/pdf"


# -- generic update/partial_update: CanManageRecetas object-permission gap --


def test_update_borrador_by_author_succeeds(auth_client, doctor_user, borrador):
    res = auth_client(doctor_user).patch(
        f"/api/recetas/{borrador.id}/", {"proxima_cita_at": None}, format="json"
    )
    assert res.status_code == 200, res.data


def test_update_borrador_by_other_doctor_forbidden(auth_client, make_user, borrador):
    from apps.accounts.models import User

    other_doctor = make_user("other-doctor-update", User.Role.DOCTOR)
    res = auth_client(other_doctor).patch(
        f"/api/recetas/{borrador.id}/", {"proxima_cita_at": None}, format="json"
    )
    assert res.status_code == 403


def test_update_emitida_via_generic_patch_forbidden_for_doctor(auth_client, doctor_user, emitida):
    # Regression: before CanManageRecetas.has_object_permission existed, any
    # Admin/Doctor could PATCH any receta at any status through the plain
    # endpoint -- an EMITIDA receta must now go through guardar_cambios
    # instead of the generic update path.
    res = auth_client(doctor_user).patch(
        f"/api/recetas/{emitida.id}/", {"proxima_cita_at": None}, format="json"
    )
    assert res.status_code == 403


def test_update_emitida_via_generic_patch_allowed_for_admin(auth_client, admin_user, emitida):
    res = auth_client(admin_user).patch(
        f"/api/recetas/{emitida.id}/", {"proxima_cita_at": None}, format="json"
    )
    assert res.status_code == 200, res.data


# -- guardar_cambios (1-hour edit window on an EMITIDA receta) ---------------


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_guardar_cambios_within_window_by_owner_doctor_succeeds(mock_pdf, auth_client, doctor_user, emitida):
    old_pdf_name = emitida.pdf.name
    res = auth_client(doctor_user).post(
        f"/api/recetas/{emitida.id}/guardar_cambios/", {"lineas": _lineas_payload()}, format="json"
    )
    assert res.status_code == 200, res.data
    emitida.refresh_from_db()
    assert emitida.estado == Receta.Estado.EMITIDA
    assert emitida.lineas.count() == 1
    assert emitida.lineas.first().nombre_impreso == "Losartan LAM 2"
    assert emitida.pdf.name != old_pdf_name


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_guardar_cambios_denied_after_window(mock_pdf, auth_client, doctor_user, emitida):
    emitida.emitida_at = timezone.now() - timedelta(hours=2)
    emitida.save(update_fields=["emitida_at"])
    res = auth_client(doctor_user).post(
        f"/api/recetas/{emitida.id}/guardar_cambios/", {"lineas": _lineas_payload()}, format="json"
    )
    assert res.status_code == 403


def test_guardar_cambios_denied_for_non_owner_doctor(auth_client, make_user, emitida):
    from apps.accounts.models import User

    other_doctor = make_user("other-doctor-gc", User.Role.DOCTOR)
    res = auth_client(other_doctor).post(
        f"/api/recetas/{emitida.id}/guardar_cambios/", {"lineas": _lineas_payload()}, format="json"
    )
    assert res.status_code == 403


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_guardar_cambios_allowed_for_admin_outside_window(mock_pdf, auth_client, admin_user, emitida):
    emitida.emitida_at = timezone.now() - timedelta(hours=5)
    emitida.save(update_fields=["emitida_at"])
    res = auth_client(admin_user).post(
        f"/api/recetas/{emitida.id}/guardar_cambios/", {"lineas": _lineas_payload()}, format="json"
    )
    assert res.status_code == 200, res.data


def test_guardar_cambios_denied_for_borrador(auth_client, doctor_user, borrador):
    _add_linea(borrador)
    res = auth_client(doctor_user).post(
        f"/api/recetas/{borrador.id}/guardar_cambios/", {"lineas": _lineas_payload()}, format="json"
    )
    assert res.status_code == 403


@patch("apps.prescriptions.views.generate_receta_pdf", return_value=b"%PDF-fake")
def test_guardar_cambios_replaces_archivos_attachment_in_place(
    mock_pdf, auth_client, doctor_user, emitida, medical_record
):
    old_name = emitida.pdf.name
    RecordImage.objects.create(
        record=medical_record, image=old_name, caption="Receta original", kind=RecordImage.Kind.PDF,
    )
    res = auth_client(doctor_user).post(
        f"/api/recetas/{emitida.id}/guardar_cambios/", {"lineas": _lineas_payload()}, format="json"
    )
    assert res.status_code == 200, res.data
    emitida.refresh_from_db()
    assert RecordImage.objects.filter(record=medical_record).count() == 1
    updated = RecordImage.objects.get(record=medical_record)
    assert updated.image.name == emitida.pdf.name
    assert updated.image.name != old_name
