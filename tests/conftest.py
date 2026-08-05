import pytest  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(username, role, **kwargs):
        return User.objects.create_user(
            username=username,
            password="pass12345",
            role=role,
            **kwargs,
        )

    return _make


@pytest.fixture
def admin_user(make_user):
    return make_user("admin", User.Role.ADMIN)


@pytest.fixture
def doctor_user(make_user):
    return make_user("doctor", User.Role.DOCTOR)


@pytest.fixture
def receptionist_user(make_user):
    return make_user("receptionist", User.Role.RECEPTIONIST)


@pytest.fixture
def it_user(make_user):
    return make_user("it", User.Role.IT)


@pytest.fixture
def nurse_user(make_user):
    return make_user("nurse", User.Role.NURSE)


@pytest.fixture
def auth_client(api_client):
    def _auth(user):
        api_client.force_authenticate(user=user)
        return api_client

    return _auth
