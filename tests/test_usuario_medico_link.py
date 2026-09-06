"""Usuario <-> Médico link feature: a Doctor/a login and a Médicos row are
the same person (see docs/planning/Requirements/UsuarioMedico/
USUARIO_MEDICO_LINK_REQUIREMENTS.md). Covers the 7 acceptance-checklist
items plus supporting regressions."""

from django.contrib.auth import get_user_model

from apps.doctors.models import DoctorProfile

User = get_user_model()


def test_create_user_doctor_role_without_profile_payload_fails(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {"username": "newdoc", "password": "Str0ngPass123!", "role": "DOCTOR"},
        format="json",
    )
    assert res.status_code == 400, res.data
    assert "doctor_profile" in res.data


def test_create_user_non_doctor_role_unaffected(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {"username": "newrec", "password": "Str0ngPass123!", "role": "RECEPTIONIST"},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert DoctorProfile.objects.count() == 0


def test_create_doctor_profile_without_user_succeeds(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {"first_name": "Ana", "last_name": "Torres", "contact_phone": "8095550001"},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["user_id"] is None
    assert res.data["username"] == ""


def test_create_doctor_profile_with_create_account_creates_linked_user(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {
            "first_name": "Ana",
            "last_name": "Torres",
            "contact_phone": "8095550001",
            "create_account": {
                "username": "ana.torres",
                "password": "Str0ngPass123!",
                "email": "ana@example.com",
            },
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    user = User.objects.get(username="ana.torres")
    assert user.role == User.Role.DOCTOR
    assert user.check_password("Str0ngPass123!")
    # the médico's own name is authoritative -- the new account it created
    # should carry it, not be left blank.
    assert user.first_name == "Ana"
    assert user.last_name == "Torres"
    profile = DoctorProfile.objects.get(pk=res.data["id"])
    assert profile.user_id == user.id


def test_users_link_mode_selects_existing_unlinked_doctor(auth_client, admin_user):
    unlinked = DoctorProfile.objects.create(first_name="", last_name="", contact_phone="8095550001")
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {
            "username": "newdoc",
            "password": "Str0ngPass123!",
            "first_name": "New",
            "last_name": "Doctor",
            "role": "DOCTOR",
            "doctor_profile": {"mode": "link", "doctor_profile_id": unlinked.id},
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    unlinked.refresh_from_db()
    user = User.objects.get(username="newdoc")
    assert unlinked.user_id == user.id
    # médico's name was blank -> fell back to being seeded from the user
    assert unlinked.first_name == "New"
    assert unlinked.last_name == "Doctor"


def test_users_link_mode_overwrites_user_name_with_existing_medico_name(auth_client, admin_user):
    # The médico is authoritative: linking it to a user pushes ITS name
    # onto the user, overwriting whatever was typed in the Usuarios form.
    unlinked = DoctorProfile.objects.create(
        first_name="Existing", last_name="Name", contact_phone="8095550001"
    )
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {
            "username": "newdoc",
            "password": "Str0ngPass123!",
            "first_name": "Typed",
            "last_name": "InForm",
            "role": "DOCTOR",
            "doctor_profile": {"mode": "link", "doctor_profile_id": unlinked.id},
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    unlinked.refresh_from_db()
    assert unlinked.first_name == "Existing"
    assert unlinked.last_name == "Name"
    user = User.objects.get(username="newdoc")
    assert user.first_name == "Existing"
    assert user.last_name == "Name"


def test_users_link_mode_rejects_already_linked_profile(auth_client, admin_user, doctor_user):
    linked = DoctorProfile.objects.create(
        user=doctor_user, first_name="Already", last_name="Linked", contact_phone="8095550001"
    )
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {
            "username": "newdoc",
            "password": "Str0ngPass123!",
            "role": "DOCTOR",
            "doctor_profile": {"mode": "link", "doctor_profile_id": linked.id},
        },
        format="json",
    )
    assert res.status_code == 400, res.data


def test_users_link_mode_rejects_inactive_profile(auth_client, admin_user):
    inactive = DoctorProfile.objects.create(
        first_name="Inactive", last_name="Doc", contact_phone="8095550001", active=False
    )
    res = auth_client(admin_user).post(
        "/api/auth/users/",
        {
            "username": "newdoc",
            "password": "Str0ngPass123!",
            "role": "DOCTOR",
            "doctor_profile": {"mode": "link", "doctor_profile_id": inactive.id},
        },
        format="json",
    )
    assert res.status_code == 400, res.data


def test_unlink_keeps_both_rows(auth_client, admin_user, doctor_user):
    profile = DoctorProfile.objects.create(
        user=doctor_user, first_name="Doc", last_name="Linked", contact_phone="8095550001"
    )
    res = auth_client(admin_user).post(
        f"/api/doctors/profiles/{profile.id}/unlink_account/", {}, format="json"
    )
    assert res.status_code == 200, res.data
    profile.refresh_from_db()
    assert profile.user_id is None
    doctor_user.refresh_from_db()
    assert User.objects.filter(pk=doctor_user.pk).exists()
    assert doctor_user.is_active is True


def test_unlink_requires_admin(auth_client, it_user, doctor_user):
    profile = DoctorProfile.objects.create(
        user=doctor_user, first_name="Doc", last_name="Linked", contact_phone="8095550001"
    )
    res = auth_client(it_user).post(
        f"/api/doctors/profiles/{profile.id}/unlink_account/", {}, format="json"
    )
    assert res.status_code == 403


def test_one_to_one_enforced_at_db_level(auth_client, admin_user, doctor_user):
    DoctorProfile.objects.create(
        user=doctor_user, first_name="First", contact_phone="8095550001"
    )
    res = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {"first_name": "Second", "contact_phone": "8095550002", "user": doctor_user.id},
        format="json",
    )
    assert res.status_code == 400, res.data
    assert DoctorProfile.objects.filter(user=doctor_user).count() == 1


def test_role_change_away_from_doctor_auto_unlinks(auth_client, admin_user, doctor_user):
    profile = DoctorProfile.objects.create(
        user=doctor_user, first_name="Doc", last_name="Linked", contact_phone="8095550001"
    )
    res = auth_client(admin_user).patch(
        f"/api/auth/users/{doctor_user.id}/",
        {"role": "RECEPTIONIST"},
        format="json",
    )
    assert res.status_code == 200, res.data
    profile.refresh_from_db()
    assert profile.user_id is None
    assert DoctorProfile.objects.filter(pk=profile.pk).exists()


def test_doctor_profile_serializer_rejects_non_doctor_role_user(auth_client, admin_user, receptionist_user):
    res = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {
            "first_name": "Wrong",
            "last_name": "Role",
            "contact_phone": "8095550001",
            "user": receptionist_user.id,
        },
        format="json",
    )
    assert res.status_code == 400, res.data


def test_license_number_optional_multiple_blank_allowed(auth_client, admin_user):
    first = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {"first_name": "Doc", "last_name": "One", "contact_phone": "8095550001"},
        format="json",
    )
    second = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {"first_name": "Doc", "last_name": "Two", "contact_phone": "8095550002"},
        format="json",
    )
    assert first.status_code == 201, first.data
    assert second.status_code == 201, second.data


def test_prescribing_doctor_resolves_via_reverse_accessor_post_unlink(doctor_user):
    profile = DoctorProfile.objects.create(
        user=doctor_user, first_name="Doc", last_name="Linked", contact_phone="8095550001"
    )
    assert getattr(doctor_user, "doctor_profile", None) == profile

    profile.user = None
    profile.save(update_fields=["user"])
    doctor_user.refresh_from_db()
    assert getattr(doctor_user, "doctor_profile", None) is None


def test_editing_linked_medico_name_updates_user(auth_client, admin_user, doctor_user):
    profile = DoctorProfile.objects.create(
        user=doctor_user, first_name="Old", last_name="Name", contact_phone="8095550001"
    )
    res = auth_client(admin_user).patch(
        f"/api/doctors/profiles/{profile.id}/",
        {"first_name": "New", "last_name": "Name"},
        format="json",
    )
    assert res.status_code == 200, res.data
    doctor_user.refresh_from_db()
    assert doctor_user.first_name == "New"
    assert doctor_user.last_name == "Name"


def test_create_account_sets_new_user_name_from_medico(auth_client, admin_user):
    res = auth_client(admin_user).post(
        "/api/doctors/profiles/",
        {
            "first_name": "Carla",
            "last_name": "Mejia",
            "contact_phone": "8095550001",
            "create_account": {
                "username": "carla.mejia",
                "password": "Str0ngPass123!",
            },
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    user = User.objects.get(username="carla.mejia")
    assert user.first_name == "Carla"
    assert user.last_name == "Mejia"
