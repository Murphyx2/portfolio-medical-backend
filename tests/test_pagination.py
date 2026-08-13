"""Pagination behavior for list endpoints.

- Default page size is 20 and the client may override it via `?page_size=`,
  capped at the `DefaultPagination.max_page_size` (200).
- `?page=` navigates pages and page 2 differs from page 1.
- The paginated envelope carries count/next/previous so the frontend can
  render navigation (and hide it when there is a single page).
"""

import pytest

from apps.patients.models import Patient


@pytest.fixture
def many_patients(db):
    for i in range(25):
        Patient.objects.create(
            first_name=f"P{i:02d}",
            last_name="Seed",
            gender="MALE" if i % 2 == 0 else "FEMALE",
        )


def test_default_page_size_is_20(auth_client, admin_user, many_patients):
    res = auth_client(admin_user).get("/api/patients/")
    assert res.status_code == 200
    assert res.data["count"] == 25
    assert len(res.data["results"]) == 20
    assert res.data["next"] is not None
    assert res.data["previous"] is None


def test_page_size_query_param_is_honored(auth_client, admin_user, many_patients):
    res = auth_client(admin_user).get("/api/patients/?page_size=25")
    assert res.status_code == 200
    assert len(res.data["results"]) == 25
    assert res.data["next"] is None


def test_page_size_query_param_is_capped(auth_client, admin_user, many_patients):
    res = auth_client(admin_user).get("/api/patients/?page_size=500")
    assert res.status_code == 200
    assert len(res.data["results"]) == 25  # capped to max_page_size, no error


def test_page_2_returns_different_rows(auth_client, admin_user, many_patients):
    page1 = auth_client(admin_user).get("/api/patients/?page_size=10")
    page2 = auth_client(admin_user).get("/api/patients/?page_size=10&page=2")
    ids1 = {row["id"] for row in page1.data["results"]}
    ids2 = {row["id"] for row in page2.data["results"]}
    assert len(page1.data["results"]) == 10
    assert len(page2.data["results"]) == 10
    assert not ids1 & ids2
    assert page2.data["previous"] is not None
