from django.contrib.auth import get_user_model
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import User
from apps.core.services import can_view_inactive, user_accessible_center_ids


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)


class CanViewInactive(BasePermission):
    """Gate for the restore action and anything else that touches deactivated
    rows. Wraps `can_view_inactive()` rather than checking the role directly
    so this and query-time visibility can never drift apart.
    """

    def has_permission(self, request, view):
        return can_view_inactive(request.user)


class IsIT(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_it)


class IsAdminOrIT(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin or request.user.is_it)
        )


class IsDoctor(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_doctor)


class IsReceptionist(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_receptionist
        )


class CanDeletePatient(BasePermission):
    """Only admins and doctors may delete patients (receptionists excluded)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin or request.user.is_doctor)
        )


class CanDeleteAppointments(BasePermission):
    """Only admins and doctors may delete appointments (receptionists excluded)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin or request.user.is_doctor)
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_doctor", False) and obj.doctor.user_id != user.id:
            return False
        return True


class CanManageMedicines(BasePermission):
    """Admins, IT, and receptionists may create/update medicines; delete
    stays IsAdminOrIT-only (see medicines/views.py get_permissions)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin or request.user.is_it or request.user.is_receptionist)
        )


class CanManageRooms(BasePermission):
    """Admins and IT may create/update rooms; receptionists may update
    existing rooms but not create new ones (delete stays IsAdminOrIT-only,
    see rooms/views.py get_permissions)."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method == "POST":
            return request.user.is_admin or request.user.is_it
        return request.user.is_admin or request.user.is_it or request.user.is_receptionist


class IsAdminOrCenterManager(BasePermission):
    """Admins and center managers may manage services."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_admin or request.user.is_center_manager)
        )


class IsDoctorOrReceptionist(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_doctor or request.user.is_receptionist)
        )


class IsDoctorOrNurse(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_doctor or request.user.is_nurse)
        )


class CanManageRecords(BasePermission):
    """Doctors, nurses, and admins may create/update medical records.

    Object-level checks (M-02): updates/deletes stay inside the actor's scope —
    admins anywhere; doctors in their approved centers (or records they
    created); nurses only on records they created (the data model has no
    nurse-to-center relationship yet, so "own records" is the safest scope).
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_doctor
                or request.user.is_nurse
                or request.user.is_admin
            )
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_admin", False):
            return True
        owner_id = getattr(obj, "created_by_id", None)
        if owner_id is None:
            owner_id = getattr(obj, "uploaded_by_id", None)
        if owner_id is None:
            owner_id = getattr(obj, "doctor_id", None)
        if getattr(user, "is_doctor", False):
            center_ids = user_accessible_center_ids(user)
            center_id = getattr(obj, "center_id", None)
            return center_id in center_ids or owner_id == user.id
        if getattr(user, "is_nurse", False):
            return owner_id == user.id
        return False


class IsStaffUser(BasePermission):
    """Any authenticated staff role (all roles except none)."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class CanManageAppointments(BasePermission):
    """Doctors, receptionists, and admins may create/update appointments.

    Object-level: a doctor may only write to appointments assigned to them
    (mirrors CanManageEncounters) -- the center-shared read scope in
    AppointmentViewSet.get_queryset() must not imply write access to a
    colleague's appointment at the same center.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_doctor
                or request.user.is_receptionist
                or request.user.is_admin
            )
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_doctor", False) and obj.doctor.user_id != user.id:
            return False
        return True


class IsCenterManager(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_center_manager
        )


def is_staff_role(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.role in (
        User.Role.ADMIN,
        User.Role.DOCTOR,
        User.Role.RECEPTIONIST,
        User.Role.IT,
        User.Role.NURSE,
        User.Role.CENTER_MANAGER,
    )


class CanManageEncounters(BasePermission):
    """Admin/doctor/receptionist/nurse/center_manager may create/update
    encounters (IT stays read-only, matching its read-only PII posture
    elsewhere). Object-level: doctors are restricted to their own
    encounters, and no one may edit an encounter once it's COMPLETED/
    CANCELLED or has a COMPLETED service line (billed/administered work
    shouldn't be rewritten after the fact).
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user.is_admin
            or request.user.is_doctor
            or request.user.is_receptionist
            or request.user.is_nurse
            or request.user.is_center_manager
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_doctor", False) and obj.doctor.user_id != user.id:
            return False
        if not getattr(user, "is_admin", False):
            if obj.status in ("COMPLETED", "CANCELLED"):
                return False
            if obj.services.filter(status="COMPLETED").exists():
                return False
        return True


class PatientDataPermission(BasePermission):
    """
    Patient data is sensitive: writes require Admin/Doctor/Receptionist; reads
    are allowed for authenticated staff only, and doctors see full records
    while others see redacted summaries (enforced by serializers).
    """

    def has_permission(self, request, view):
        if not is_staff_role(request.user):
            return False
        if request.method in SAFE_METHODS:
            return True
        return (
            request.user.is_admin
            or request.user.is_doctor
            or request.user.is_receptionist
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return is_staff_role(request.user)
        return request.user.is_admin or request.user.is_doctor or request.user.is_receptionist
