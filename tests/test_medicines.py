"""Medicines RBAC: Admin/IT/Receptionist may create/update; delete stays
Admin/IT-only (receptionist excluded from delete, see CanManageMedicines).
"""

from apps.medicines.models import Medicine


def _payload(**overrides):
    data = {
        "generic_name": "Acetaminophen",
        "commercial_name": "Tylenol",
        "concentration": "500mg",
    }
    data.update(overrides)
    return data


def test_receptionist_can_create_medicine(auth_client, receptionist_user):
    res = auth_client(receptionist_user).post("/api/medicines/", _payload(), format="json")
    assert res.status_code == 201, res.data


def test_receptionist_can_update_medicine(auth_client, receptionist_user):
    med = Medicine.objects.create(generic_name="A", commercial_name="B")
    res = auth_client(receptionist_user).patch(
        f"/api/medicines/{med.id}/", {"commercial_name": "C"}, format="json"
    )
    assert res.status_code == 200, res.data
    assert res.data["commercial_name"] == "C"


def test_receptionist_cannot_delete_medicine(auth_client, receptionist_user):
    med = Medicine.objects.create(generic_name="A", commercial_name="B")
    res = auth_client(receptionist_user).delete(f"/api/medicines/{med.id}/")
    assert res.status_code == 403, res.data


def test_doctor_can_create_medicine(auth_client, doctor_user):
    res = auth_client(doctor_user).post("/api/medicines/", _payload(), format="json")
    assert res.status_code == 201, res.data


def test_nurse_can_create_medicine(auth_client, nurse_user):
    res = auth_client(nurse_user).post("/api/medicines/", _payload(), format="json")
    assert res.status_code == 201, res.data


def test_doctor_cannot_delete_medicine(auth_client, doctor_user):
    med = Medicine.objects.create(generic_name="A", commercial_name="B")
    res = auth_client(doctor_user).delete(f"/api/medicines/{med.id}/")
    assert res.status_code == 403, res.data


def test_admin_can_delete_medicine(auth_client, admin_user):
    med = Medicine.objects.create(generic_name="A", commercial_name="B")
    res = auth_client(admin_user).delete(f"/api/medicines/{med.id}/")
    assert res.status_code == 204, res.data


def test_create_medicine_without_legacy_concentration_field(auth_client, admin_user):
    # Regression: the Medicamentos catalog UI stopped sending the legacy
    # `concentration` string once concentracion_valor/concentracion_unidad
    # shipped, but Medicine.unique_together forces DRF to require
    # `concentration` by default regardless of the model's blank=True --
    # this used to 400 with "concentration: Este campo es requerido."
    res = auth_client(admin_user).post(
        "/api/medicines/",
        {
            "generic_name": "Ibuprofeno",
            "commercial_name": "Test Brand",
            "concentracion_valor": "200",
            "concentracion_unidad": "mg",
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["concentration"] == "200mg"
