from django.contrib.auth import get_user_model
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import User
from apps.core.services import can_view_inactive


def is_staff_role(user) -> bool:
    """The one canonical definition of "staff" -- explicit 6-role
    membership. `IsStaffUser` delegates here instead of re-checking
    `is_authenticated` on its own, so a future 7th role only needs updating
    in one place instead of silently diverging between the two."""
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


def is_owner_doctor(user, obj) -> bool:
    """True unless `user` is a doctor who doesn't own `obj.doctor` --
    previously copy-pasted identically across CanDeleteAppointments,
    CanManageAppointments, and CanManageEncounters."""
    return not (getattr(user, "is_doctor", False) and obj.doctor.user_id != user.id)


class RoleUnionPermission(BasePermission):
    """Composable base for the many "one of these roles" permission
    classes that used to each hand-write the same
    `request.user and request.user.is_authenticated and (role or role...)`
    body. Subclasses just set `allowed_roles`."""

    allowed_roles: tuple = ()

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in self.allowed_roles
        )


class IsAdmin(RoleUnionPermission):
    allowed_roles = (User.Role.ADMIN,)


class CanViewInactive(BasePermission):
    """Gate for the restore action and anything else that touches deactivated
    rows. Wraps `can_view_inactive()` rather than checking the role directly
    so this and query-time visibility can never drift apart.
    """

    def has_permission(self, request, view):
        return can_view_inactive(request.user)


class IsIT(RoleUnionPermission):
    allowed_roles = (User.Role.IT,)


class IsAdminOrIT(RoleUnionPermission):
    allowed_roles = (User.Role.ADMIN, User.Role.IT)


class IsAdminOrITOrCenterManager(RoleUnionPermission):
    """Doctor profile writes: ADMIN/IT manage the general fields; a
    CENTER_MANAGER is admitted at this view-permission layer too, but
    DoctorProfileSerializer.validate() confines them to the `services` field
    only -- this class alone doesn't distinguish which fields a request
    touches (DRF permissions are method-wide, not field-scoped)."""

    allowed_roles = (User.Role.ADMIN, User.Role.IT, User.Role.CENTER_MANAGER)


class IsDoctor(RoleUnionPermission):
    allowed_roles = (User.Role.DOCTOR,)


class IsReceptionist(RoleUnionPermission):
    allowed_roles = (User.Role.RECEPTIONIST,)


class CanDeletePatient(RoleUnionPermission):
    """Only admins and doctors may delete patients (receptionists excluded)."""

    allowed_roles = (User.Role.ADMIN, User.Role.DOCTOR)


class CanDeleteAppointments(RoleUnionPermission):
    """Only admins and doctors may delete appointments (receptionists excluded)."""

    allowed_roles = (User.Role.ADMIN, User.Role.DOCTOR)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return is_owner_doctor(request.user, obj)


class CanManageMedicines(RoleUnionPermission):
    """Admins, IT, and receptionists may create/update medicines; delete
    stays IsAdminOrIT-only (see medicines/views.py get_permissions)."""

    allowed_roles = (User.Role.ADMIN, User.Role.IT, User.Role.RECEPTIONIST)


class CanManageRooms(BasePermission):
    """Admins and IT may create/update rooms; receptionists may update
    existing rooms but not create new ones (delete stays IsAdminOrIT-only,
    see rooms/views.py get_permissions). Method-conditional role sets don't
    fit the flat RoleUnionPermission shape, so this stays hand-written."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method == "POST":
            return request.user.is_admin or request.user.is_it
        return request.user.is_admin or request.user.is_it or request.user.is_receptionist


class IsAdminOrCenterManager(RoleUnionPermission):
    """Admins and center managers may manage services."""

    allowed_roles = (User.Role.ADMIN, User.Role.CENTER_MANAGER)


class IsDoctorOrReceptionist(RoleUnionPermission):
    allowed_roles = (User.Role.DOCTOR, User.Role.RECEPTIONIST)


class IsDoctorOrNurse(RoleUnionPermission):
    allowed_roles = (User.Role.DOCTOR, User.Role.NURSE)


class CanManageRecords(RoleUnionPermission):
    """Doctors, nurses, and admins may create/update medical records.

    Object-level checks (M-02): updates/deletes stay inside the actor's scope —
    admins anywhere; doctors in their approved centers (or records they
    created); nurses only on records they created (the data model has no
    nurse-to-center relationship yet, so "own records" is the safest scope).
    """

    allowed_roles = (User.Role.DOCTOR, User.Role.NURSE, User.Role.ADMIN)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_admin", False):
            return True
        # Doctors have unrestricted read/write access to every record --
        # unlike other apps (e.g. Appointments), records are not scoped to a
        # doctor's own centers here.
        if getattr(user, "is_doctor", False):
            return True
        if getattr(user, "is_nurse", False):
            owner_id = getattr(obj, "created_by_id", None)
            if owner_id is None:
                owner_id = getattr(obj, "uploaded_by_id", None)
            if owner_id is None:
                owner_id = getattr(obj, "doctor_id", None)
            return owner_id == user.id
        return False


class IsAdminDoctorOrNurse(RoleUnionPermission):
    """Records read access -- ADMIN/DOCTOR/NURSE only. RECEPTIONIST, IT, and
    CENTER_MANAGER can no longer see medical records at all (narrower than
    the general IsStaffUser 6-role set every other view uses)."""

    allowed_roles = (User.Role.ADMIN, User.Role.DOCTOR, User.Role.NURSE)


class IsStaffUser(BasePermission):
    """Any authenticated staff role -- delegates to `is_staff_role`, the one
    canonical 6-role membership definition, instead of re-checking
    `is_authenticated` independently (the two were behaviorally identical
    but independently maintained, a future-drift risk if a 7th role is ever
    added to one and not the other)."""

    def has_permission(self, request, view):
        return is_staff_role(request.user)


class CanManageAppointments(RoleUnionPermission):
    """Doctors, receptionists, and admins may create/update appointments.

    Object-level: a doctor may only write to appointments assigned to them
    (mirrors CanManageEncounters) -- the center-shared read scope in
    AppointmentViewSet.get_queryset() must not imply write access to a
    colleague's appointment at the same center.
    """

    allowed_roles = (User.Role.DOCTOR, User.Role.RECEPTIONIST, User.Role.ADMIN)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return is_owner_doctor(request.user, obj)


class CanCancelAppointment(RoleUnionPermission):
    """Only receptionists or admins may cancel an appointment. Was an inline
    `self.permission_denied(...)` check inside AppointmentViewSet.cancel()
    (B7) -- moved to a permission class so it's checked at dispatch() time
    like every other write gate, instead of after get_object()."""

    allowed_roles = (User.Role.RECEPTIONIST, User.Role.ADMIN)


class CanCompleteAppointment(RoleUnionPermission):
    """Only doctors or admins may complete an appointment; a doctor may only
    complete their own (mirrors CanManageAppointments' object-level check --
    was previously enforced there since AppointmentViewSet.complete() ran
    through write_permission_classes=[CanManageAppointments] on top of its
    own inline role check)."""

    allowed_roles = (User.Role.DOCTOR, User.Role.ADMIN)

    def has_object_permission(self, request, view, obj):
        return is_owner_doctor(request.user, obj)


class IsCenterManager(RoleUnionPermission):
    allowed_roles = (User.Role.CENTER_MANAGER,)


class CanManageEncounters(BasePermission):
    """Admin/doctor/receptionist/nurse/center_manager may create/update
    encounters (IT stays read-only, matching its read-only PII posture
    elsewhere). Object-level: doctors are restricted to their own
    encounters, and no one may edit an encounter once it's COMPLETED/
    CANCELLED or has a COMPLETED service line (billed/administered work
    shouldn't be rewritten after the fact) -- see
    Encounter.is_locked_for_edit().
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
        if not is_owner_doctor(request.user, obj):
            return False
        if not getattr(request.user, "is_admin", False) and obj.is_locked_for_edit():
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
