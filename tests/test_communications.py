import hashlib
import hmac
import json
from datetime import timedelta

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.communications.models import CommunicationsSettings, Delivery, Message, OptOut, Template
from apps.doctors.models import DoctorProfile
from apps.patients.models import Patient


def _patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "birth_date": "1990-01-01",
        "cedula": overrides.pop("cedula", "00100000001"),
        "phone": "8095550100",
        "whatsapp_opt_in": True,
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _doctor(user, **overrides):
    data = {"license_number": f"LIC-{user.id}", "contact_phone": "8095550000"}
    data.update(overrides)
    return DoctorProfile.objects.create(user=user, **data)


def _appointment(patient, doctor, created_by, **overrides):
    data = {
        "patient": patient,
        "doctor": doctor,
        "date_time": timezone.now() + timedelta(days=1),
        "status": Appointment.Status.SCHEDULED,
        "created_by": created_by,
    }
    data.update(overrides)
    return Appointment.objects.create(**data)


def _enable_whatsapp(**overrides):
    settings_obj, _ = CommunicationsSettings.objects.get_or_create(pk=1)
    defaults = {
        "whatsapp_master_enabled": True,
        "whatsapp_phone_number_id": "123456",
        "whatsapp_access_token": "test-token",
        "whatsapp_app_secret": "test-secret",
    }
    defaults.update(overrides)
    for field, value in defaults.items():
        setattr(settings_obj, field, value)
    settings_obj.save()
    return settings_obj


def _active_template(kind, channel=Template.Channel.WHATSAPP):
    return Template.objects.create(
        channel=channel,
        kind=kind,
        provider_name=f"tmpl_{kind.lower()}",
        language="es_DO",
        variables_json=["nombre", "clinica", "fecha", "hora", "telefono"],
        is_active=True,
    )


# ---------------------------------------------------------------------------
# Staff email compose permissions
# ---------------------------------------------------------------------------


def test_doctor_cannot_send_alerta(auth_client, doctor_user, receptionist_user):
    res = auth_client(doctor_user).post(
        "/api/communications/messages/",
        {
            "channel": "EMAIL",
            "audience": "STAFF",
            "kind": "ALERTA",
            "subject": "Test",
            "body": "Body",
            "recipients": {"all_staff": True},
        },
        format="json",
    )
    assert res.status_code == 400


def test_doctor_cannot_send_normal_priority_marked_alerta(auth_client, doctor_user):
    res = auth_client(doctor_user).post(
        "/api/communications/messages/",
        {
            "channel": "EMAIL",
            "audience": "STAFF",
            "kind": "AVISO",
            "priority": "ALERTA",
            "subject": "Test",
            "body": "Body",
            "recipients": {"all_staff": True},
        },
        format="json",
    )
    assert res.status_code == 400


def test_nurse_cannot_post_message(auth_client, nurse_user):
    res = auth_client(nurse_user).post(
        "/api/communications/messages/",
        {
            "channel": "EMAIL",
            "audience": "STAFF",
            "kind": "AVISO",
            "subject": "Test",
            "body": "Body",
            "recipients": {"all_staff": True},
        },
        format="json",
    )
    assert res.status_code == 403


def test_admin_email_skips_users_without_email(auth_client, admin_user, make_user):
    from apps.accounts.models import User

    make_user("noemail", User.Role.NURSE, email="")
    make_user("withemail", User.Role.NURSE, email="withemail@example.com")

    res = auth_client(admin_user).post(
        "/api/communications/messages/",
        {
            "channel": "EMAIL",
            "audience": "STAFF",
            "kind": "AVISO",
            "subject": "Test",
            "body": "Body",
            "recipients": {"all_staff": True},
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["skipped_no_email"] >= 1
    message = Message.objects.get(pk=res.data["id"])
    assert not Delivery.objects.filter(message=message, user__email="").exists()
    assert Delivery.objects.filter(message=message, user__username="withemail").exists()


def test_message_requires_recipients(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/communications/messages/",
        {
            "channel": "EMAIL",
            "audience": "STAFF",
            "kind": "AVISO",
            "subject": "Test",
            "body": "Body",
        },
        format="json",
    )
    assert res.status_code == 400


def test_cannot_compose_to_patient_audience(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/communications/messages/",
        {
            "channel": "EMAIL",
            "audience": "PATIENT",
            "kind": "AVISO",
            "subject": "Test",
            "body": "Body",
            "recipients": {"all_staff": True},
        },
        format="json",
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Patient WhatsApp preconditions
# ---------------------------------------------------------------------------


def test_notify_appointment_event_skips_when_master_disabled(auth_client, doctor_user, receptionist_user):
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user)
    _active_template(Template.Kind.CITA_CREADA)

    res = auth_client(doctor_user).post(f"/api/appointments/{appt.id}/confirm/")
    assert res.status_code == 200
    assert not Message.objects.filter(appointment=appt).exists()


def test_notify_appointment_event_skips_without_opt_in(auth_client, doctor_user, receptionist_user):
    _enable_whatsapp()
    doctor = _doctor(doctor_user)
    patient = _patient(whatsapp_opt_in=False)
    appt = _appointment(patient, doctor, receptionist_user)
    _active_template(Template.Kind.CITA_CREADA)

    res = auth_client(doctor_user).post(f"/api/appointments/{appt.id}/confirm/")
    assert res.status_code == 200
    assert not Message.objects.filter(appointment=appt).exists()


def test_notify_appointment_event_skips_without_template(auth_client, doctor_user, receptionist_user):
    _enable_whatsapp()
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user)

    res = auth_client(doctor_user).post(f"/api/appointments/{appt.id}/confirm/")
    assert res.status_code == 200
    assert not Message.objects.filter(appointment=appt).exists()


def test_confirm_queues_cita_creada_when_preconditions_met(auth_client, doctor_user, receptionist_user):
    _enable_whatsapp()
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user)
    _active_template(Template.Kind.CITA_CREADA)

    res = auth_client(doctor_user).post(f"/api/appointments/{appt.id}/confirm/")
    assert res.status_code == 200
    message = Message.objects.get(appointment=appt, kind=Template.Kind.CITA_CREADA)
    assert message.status == Message.Status.QUEUED
    delivery = Delivery.objects.get(message=message)
    assert delivery.address == "+18095550100"


def test_cancel_queues_cancelada_and_cancels_pending_reminder(auth_client, doctor_user, receptionist_user):
    _enable_whatsapp()
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user, status=Appointment.Status.CONFIRMED)
    _active_template(Template.Kind.CITA_CANCELADA)
    reminder_template = _active_template(Template.Kind.CITA_RECORDATORIO)
    pending_reminder = Message.objects.create(
        channel=Message.Channel.WHATSAPP,
        audience=Message.Audience.PATIENT,
        kind=Template.Kind.CITA_RECORDATORIO,
        template=reminder_template,
        status=Message.Status.QUEUED,
        appointment=appt,
    )
    Delivery.objects.create(message=pending_reminder, patient=patient, appointment=appt, address="+18095550100")

    res = auth_client(doctor_user).post(
        f"/api/appointments/{appt.id}/cancel/", {"reason": "no longer needed"}, format="json"
    )
    assert res.status_code == 200
    assert Message.objects.filter(appointment=appt, kind=Template.Kind.CITA_CANCELADA).exists()
    pending_reminder.refresh_from_db()
    assert pending_reminder.status == Message.Status.CANCELLED


# ---------------------------------------------------------------------------
# Manual reminder + rate limit
# ---------------------------------------------------------------------------


def test_manual_reminder_rate_limited(auth_client, receptionist_user, doctor_user):
    _enable_whatsapp()
    doctor = _doctor(doctor_user)
    patient = _patient()
    appt = _appointment(patient, doctor, receptionist_user, status=Appointment.Status.CONFIRMED)
    _active_template(Template.Kind.CITA_RECORDATORIO)

    message = Message.objects.create(
        channel=Message.Channel.WHATSAPP,
        audience=Message.Audience.PATIENT,
        kind=Template.Kind.CITA_RECORDATORIO,
        status=Message.Status.SENT,
        appointment=appt,
    )
    Delivery.objects.create(
        message=message,
        patient=patient,
        appointment=appt,
        address="+18095550100",
        status=Delivery.Status.SENT,
        sent_at=timezone.now(),
    )

    res = auth_client(receptionist_user).post(f"/api/appointments/{appt.id}/send_whatsapp_reminder/")
    assert res.status_code == 400


def test_manual_reminder_disabled_without_opt_in(auth_client, receptionist_user, doctor_user):
    _enable_whatsapp()
    doctor = _doctor(doctor_user)
    patient = _patient(whatsapp_opt_in=False)
    appt = _appointment(patient, doctor, receptionist_user, status=Appointment.Status.CONFIRMED)
    _active_template(Template.Kind.CITA_RECORDATORIO)

    res = auth_client(receptionist_user).post(f"/api/appointments/{appt.id}/send_whatsapp_reminder/")
    assert res.status_code == 400
    assert "WhatsApp" in res.data["detail"]


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_rejects_missing_signature(db, api_client):
    _enable_whatsapp()
    res = api_client.post(
        "/api/communications/webhook/whatsapp/", data=json.dumps({}), content_type="application/json"
    )
    assert res.status_code == 403


def test_webhook_opt_out_keyword(db, api_client):
    _enable_whatsapp()
    patient = _patient()
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [{"from": "18095550100", "text": {"body": "SALIR"}}]
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload).encode()
    res = api_client.post(
        "/api/communications/webhook/whatsapp/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=_sign("test-secret", body),
    )
    assert res.status_code == 200
    patient.refresh_from_db()
    assert patient.whatsapp_opt_in is False
    assert OptOut.objects.filter(patient=patient).exists()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_admin_only(auth_client, it_user, admin_user):
    res = auth_client(it_user).get("/api/communications/settings/")
    assert res.status_code == 403

    res = auth_client(admin_user).get("/api/communications/settings/")
    assert res.status_code == 200


def test_settings_patch_does_not_wipe_token_on_empty_value(auth_client, admin_user):
    client = auth_client(admin_user)
    res = client.patch(
        "/api/communications/settings/",
        {"whatsapp_access_token": "secret-token-value"},
        format="json",
    )
    assert res.status_code == 200
    assert "whatsapp_access_token" not in res.data
    assert res.data["whatsapp_access_token_last4"] == "alue"

    res = client.patch(
        "/api/communications/settings/",
        {"from_name": "Clinica X"},
        format="json",
    )
    assert res.status_code == 200
    settings_obj = CommunicationsSettings.objects.get(pk=1)
    assert settings_obj.whatsapp_access_token == "secret-token-value"
