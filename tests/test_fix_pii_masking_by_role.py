"""Fix P2 / H-04: GET /api/patients/{id}/ PII masking by role.

ADMIN, DOCTOR, NURSE and RECEPTIONIST must see full phone/address/email.
IT and CENTER_MANAGER must see masked values (e.g. "80••••00", "jo••••om").
"""

from apps.communications.models import Delivery, Message
from apps.patients.models import Patient

MASK = "••••"
FULL = {
    "phone": "8095550100",
    "address": "123 Main St, Springfield",
    "email": "jane.doe@example.com",
}


def _make_patient(**overrides):
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "gender": "FEMALE",
        "phone": FULL["phone"],
        "address": FULL["address"],
        "email": FULL["email"],
    }
    data.update(overrides)
    return Patient.objects.create(**data)


def _masked(patient_id, auth_client, user):
    res = auth_client(user).get(f"/api/patients/{patient_id}/")
    assert res.status_code == 200, res.data
    data = res.data
    assert data["phone"] != FULL["phone"] and MASK in data["phone"]
    assert data["email"] != FULL["email"] and MASK in data["email"]
    assert data["address"] != FULL["address"] and MASK in data["address"]
    return data


def _full(patient_id, auth_client, user):
    res = auth_client(user).get(f"/api/patients/{patient_id}/")
    assert res.status_code == 200, res.data
    data = res.data
    assert data["phone"] == FULL["phone"]
    assert data["email"] == FULL["email"]
    assert data["address"] == FULL["address"]
    return data


def test_it_sees_masked_pii(auth_client, it_user, receptionist_user):
    patient = _make_patient()
    data = _masked(patient.id, auth_client, it_user)
    # exact masking shape: "xx••••yy"
    assert data["phone"].startswith("80") and data["phone"].endswith("00")
    assert data["email"].startswith("ja") and data["email"].endswith("om")
    assert data["address"].startswith("12") and data["address"].endswith("ld")


def test_receptionist_sees_full_pii(auth_client, receptionist_user):
    patient = _make_patient()
    _full(patient.id, auth_client, receptionist_user)


def test_center_manager_sees_full_pii(auth_client, receptionist_user, make_user):
    # CENTER_MANAGER is admin-equivalent app-wide (except Settings edit).
    cm_user = make_user("cm", "CENTER_MANAGER")
    patient = _make_patient()
    _full(patient.id, auth_client, cm_user)


def test_doctor_sees_full_pii(auth_client, doctor_user):
    patient = _make_patient()
    _full(patient.id, auth_client, doctor_user)


def test_nurse_sees_full_pii(auth_client, nurse_user):
    patient = _make_patient()
    _full(patient.id, auth_client, nurse_user)


def test_admin_sees_full_pii(auth_client, admin_user):
    patient = _make_patient()
    _full(patient.id, auth_client, admin_user)


def _make_delivery(patient, created_by):
    # DeliveryViewSet.get_queryset() scopes non-admin/CM users to
    # message__created_by=user, so the requesting user must own the message.
    message = Message.objects.create(
        channel=Message.Channel.WHATSAPP,
        audience=Message.Audience.PATIENT,
        kind=Message.Kind.CITA_RECORDATORIO,
        created_by=created_by,
    )
    return Delivery.objects.create(message=message, patient=patient)


def test_it_sees_masked_delivery_patient_name(auth_client, it_user):
    # Regression for the audit finding: DeliverySerializer.get_patient_name
    # bypassed apply_masking/is_masked_role entirely (unlike every other
    # patient-PII serializer), showing IT the patient's real name.
    patient = _make_patient()
    delivery = _make_delivery(patient, it_user)
    res = auth_client(it_user).get(f"/api/communications/deliveries/{delivery.id}/")
    assert res.status_code == 200, res.data
    assert res.data["patient_name"] != patient.full_name
    assert MASK in res.data["patient_name"]


def test_center_manager_sees_full_delivery_patient_name(auth_client, make_user):
    # CENTER_MANAGER is not a masked role (apps/core/services/roles.py::is_masked_role)
    # -- only IT is masked -- so this must stay unmasked, unlike IT above.
    cm_user = make_user("cm2", "CENTER_MANAGER")
    patient = _make_patient()
    delivery = _make_delivery(patient, cm_user)
    res = auth_client(cm_user).get(f"/api/communications/deliveries/{delivery.id}/")
    assert res.status_code == 200, res.data
    assert res.data["patient_name"] == patient.full_name


def test_receptionist_sees_full_delivery_patient_name(auth_client, receptionist_user):
    patient = _make_patient()
    delivery = _make_delivery(patient, receptionist_user)
    res = auth_client(receptionist_user).get(f"/api/communications/deliveries/{delivery.id}/")
    assert res.status_code == 200, res.data
    assert res.data["patient_name"] == patient.full_name
