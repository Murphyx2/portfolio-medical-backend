"""Fix M-01: /api/schema/ and /api/docs/ are gated.

Anonymous access returns 401; ADMIN and IT get 200. Other staff roles
(e.g. DOCTOR) get 403 (authenticated but not permitted by IsAdminOrIT).
"""


def test_schema_anonymous_401(api_client):
    assert api_client.get("/api/schema/").status_code == 401


def test_docs_anonymous_401(api_client):
    assert api_client.get("/api/docs/").status_code == 401


def test_schema_admin_200(auth_client, admin_user):
    res = auth_client(admin_user).get("/api/schema/")
    assert res.status_code == 200


def test_docs_admin_200(auth_client, admin_user):
    res = auth_client(admin_user).get("/api/docs/")
    assert res.status_code == 200


def test_schema_it_200(auth_client, it_user):
    res = auth_client(it_user).get("/api/schema/")
    assert res.status_code == 200


def test_docs_it_200(auth_client, it_user):
    res = auth_client(it_user).get("/api/docs/")
    assert res.status_code == 200


def test_schema_doctor_403(auth_client, doctor_user):
    res = auth_client(doctor_user).get("/api/schema/")
    assert res.status_code == 403


def test_docs_doctor_403(auth_client, doctor_user):
    res = auth_client(doctor_user).get("/api/docs/")
    assert res.status_code == 403
