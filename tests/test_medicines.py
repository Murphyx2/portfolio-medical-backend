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


def test_admin_can_delete_medicine(auth_client, admin_user):
    med = Medicine.objects.create(generic_name="A", commercial_name="B")
    res = auth_client(admin_user).delete(f"/api/medicines/{med.id}/")
    assert res.status_code == 204, res.data
