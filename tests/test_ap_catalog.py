"""AP (Antecedentes Patologicos) catalog: APCategory/APType.

Mirrors apps.services' ServiceType/Service category+items pattern. Per spec
section 3, catalog management (write) is Admin-only -- narrower than
Services (Admin+CenterManager) -- and only Admin/Doctor/Nurse can even read
it (records-adjacent, not general staff data).
"""

import pytest
from django.db import IntegrityError

from apps.records.models import APCategory, APType


def test_seed_migration_populated_catalog(db):
    assert APCategory.objects.count() == 9
    cardio = APCategory.objects.get(name="Sistema Cardiovascular")
    assert cardio.types.count() == 5
    assert APType.objects.filter(name__startswith="Hipertensión Arterial").exists()


def test_admin_can_view_and_create_category(auth_client, admin_user):
    res = auth_client(admin_user).get("/api/ap-categories/")
    assert res.status_code == 200, res.data

    res = auth_client(admin_user).post("/api/ap-categories/", {"name": "Nueva Categoria"}, format="json")
    assert res.status_code == 201, res.data


def test_doctor_and_nurse_can_view_but_not_write_category(auth_client, doctor_user, nurse_user):
    for user in (doctor_user, nurse_user):
        res = auth_client(user).get("/api/ap-categories/")
        assert res.status_code == 200, res.data

        res = auth_client(user).post("/api/ap-categories/", {"name": "Should Fail"}, format="json")
        assert res.status_code == 403, res.data


def test_receptionist_it_center_manager_cannot_view_catalog(
    auth_client, receptionist_user, it_user, center_manager_user
):
    for user in (receptionist_user, it_user, center_manager_user):
        res = auth_client(user).get("/api/ap-categories/")
        assert res.status_code == 403, res.data


def test_admin_can_create_and_manage_type(auth_client, admin_user):
    category = APCategory.objects.create(name="Test Category")
    res = auth_client(admin_user).post(
        "/api/ap-types/", {"category": category.id, "name": "Test Type"}, format="json"
    )
    assert res.status_code == 201, res.data
    assert res.data["category_name"] == "Test Category"


def test_doctor_cannot_create_type(auth_client, doctor_user):
    category = APCategory.objects.create(name="Test Category 2")
    res = auth_client(doctor_user).post(
        "/api/ap-types/", {"category": category.id, "name": "Test Type"}, format="json"
    )
    assert res.status_code == 403, res.data


def test_type_name_unique_per_active_category(db):
    category = APCategory.objects.create(name="Uniqueness Test")
    APType.objects.create(category=category, name="Dup")
    with pytest.raises(IntegrityError):
        APType.objects.create(category=category, name="Dup")


def test_deactivating_category_hides_it_by_default(auth_client, admin_user):
    category = APCategory.objects.create(name="To Deactivate")
    res = auth_client(admin_user).delete(f"/api/ap-categories/{category.id}/")
    assert res.status_code == 204, res.data

    res = auth_client(admin_user).get("/api/ap-categories/?page_size=100")
    names = [c["name"] for c in res.data["results"]]
    assert "To Deactivate" not in names

    res = auth_client(admin_user).get("/api/ap-categories/?page_size=100&include_inactive=true")
    names = [c["name"] for c in res.data["results"]]
    assert "To Deactivate" in names
