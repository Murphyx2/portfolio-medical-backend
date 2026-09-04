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
    """True unless `user` is a doctor who doesn't own `obj` -- previously
    copy-pasted identically across CanDeleteAppointments,
    CanManageAppointments, and CanManageEncounters.

    Objects with a single `doctor` FK (Appointment) compare it directly.
    Encounter has no `doctor` of its own anymore -- coverage moved to a
    per-service-line `EncounterService.doctor` -- so ownership there means
    "assigned to at least one of this encounter's service lines"."""
    if not getattr(user, "is_doctor", False):
        return True
    if hasattr(obj, "services"):
        return obj.services.filter(doctor__user_id=user.id).exists()
    return obj.doctor.user_id == user.id


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


class IsAdminOrITReadOnly(BasePermission):
    """System settings (apps.systemsettings): ADMIN gets full read/write,
    IT and CENTER_MANAGER are admitted for safe (GET) methods only, every
    other role is denied entirely -- unlike IsAdminOrIT, IT here can never
    PATCH. CENTER_MANAGER needs read access so it can reach the Settings
    page's language section (frontend/src/utils/can.ts), but stays
    read-only on the numeric fields the same as IT."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role == User.Role.ADMIN:
            return True
        if user.role in (User.Role.IT, User.Role.CENTER_MANAGER):
            return request.method in SAFE_METHODS
        return False


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
    """Admins, doctors, and center managers (admin-equivalent) may delete
    patients (receptionists excluded)."""

    allowed_roles = (User.Role.ADMIN, User.Role.DOCTOR, User.Role.CENTER_MANAGER)


class CanDeleteAppointments(RoleUnionPermission):
    """Admins, doctors, and center managers (admin-equivalent) may delete
    appointments (receptionists excluded)."""

    allowed_roles = (User.Role.ADMIN, User.Role.DOCTOR, User.Role.CENTER_MANAGER)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return is_owner_doctor(request.user, obj)


class CanManageMedicines(RoleUnionPermission):
    """Admins, IT, receptionists, center managers (admin-equivalent), doctors,
    and nurses may create/update medicines; delete stays
    IsAdminOrITOrCenterManager-only (see medicines/views.py get_permissions).
    Doctor/Nurse were added so staff can add a new medicine to the catalog
    on the spot -- this codebase has no create-only vs. edit-only split for
    reference data, so this also grants them edit rights on any existing
    medicine, not just ones they create."""

    allowed_roles = (
        User.Role.ADMIN,
        User.Role.IT,
        User.Role.RECEPTIONIST,
        User.Role.CENTER_MANAGER,
        User.Role.DOCTOR,
        User.Role.NURSE,
    )


class IsAdminOrCenterManager(RoleUnionPermission):
    """Admins and center managers may manage services, rooms, and room
    types; every other role is read-only on these reference-data resources."""

    allowed_roles = (User.Role.ADMIN, User.Role.CENTER_MANAGER)


class IsDoctorOrReceptionist(RoleUnionPermission):
    allowed_roles = (User.Role.DOCTOR, User.Role.RECEPTIONIST)


class IsDoctorOrNurse(RoleUnionPermission):
    allowed_roles = (User.Role.DOCTOR, User.Role.NURSE)


class CanManageRecords(RoleUnionPermission):
    """Doctors, nurses, admins, and center managers may create/update
    medical records.

    Object-level checks (M-02): updates/deletes stay inside the actor's scope —
    admins (and center managers, admin-equivalent) anywhere; doctors in their
    approved centers (or records they created); nurses only on records they
    created (the data model has no nurse-to-center relationship yet, so "own
    records" is the safest scope).
    """

    allowed_roles = (
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.ADMIN,
        User.Role.CENTER_MANAGER,
    )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if getattr(user, "is_admin", False) or getattr(user, "is_center_manager", False):
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
            if owner_id is None:
                # RecordPersonalCondition/RecordFamilyCondition (Expedientes
                # Médicos AP entries) have no owner field of their own --
                # fall back to their parent MedicalRecord's creator, the same
                # scope a nurse already has for the record itself.
                record = getattr(obj, "record", None)
                owner_id = getattr(record, "created_by_id", None)
            return owner_id == user.id
        return False


class CanManageRecordEntries(RoleUnionPermission):
    """Write access to a RecordEntry (Expediente historial item): ADMIN/
    DOCTOR/NURSE, same role set as CanManageRecords, but with its own
    object-level rule since a draft and a completed entry have very
    different mutability:

    - A DRAFT may only be edited/deleted by its own author (or an admin) --
      "one draft per expediente per user" means another clinician's draft
      is invisible/untouchable to you.
    - A COMPLETED entry may only be edited (never deleted) by any allowed
      role, and only when it's still the record's single most recent
      completed entry ("Editar última entrada"); older entries are
      read-only to everyone, admin included.
    """

    allowed_roles = (
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.ADMIN,
        User.Role.CENTER_MANAGER,
    )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        is_admin = getattr(user, "is_admin", False) or getattr(user, "is_center_manager", False)
        if obj.status == obj.Status.DRAFT:
            if request.method == "DELETE":
                return is_admin or obj.author_id == user.id
            return is_admin or obj.author_id == user.id
        # COMPLETED: never deletable; editable only while still the latest.
        if request.method == "DELETE":
            return False
        latest_id = (
            obj.record.entries.filter(status=obj.Status.COMPLETED)
            .order_by("-completed_at")
            .values_list("id", flat=True)
            .first()
        )
        return obj.id == latest_id


class IsAdminDoctorOrNurse(RoleUnionPermission):
    """Records read access -- ADMIN/DOCTOR/NURSE/CENTER_MANAGER only.
    RECEPTIONIST and IT still can't see medical records at all (narrower
    than the general IsStaffUser 6-role set every other view uses)."""

    allowed_roles = (
        User.Role.ADMIN,
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.CENTER_MANAGER,
    )


class IsStaffUser(BasePermission):
    """Any authenticated staff role -- delegates to `is_staff_role`, the one
    canonical 6-role membership definition, instead of re-checking
    `is_authenticated` independently (the two were behaviorally identical
    but independently maintained, a future-drift risk if a 7th role is ever
    added to one and not the other)."""

    def has_permission(self, request, view):
        return is_staff_role(request.user)


class CanManageAppointments(RoleUnionPermission):
    """Doctors, nurses, receptionists, center managers, and admins may
    create/update appointments.

    Object-level: a doctor may only write to appointments assigned to them
    (mirrors CanManageEncounters) -- the center-shared read scope in
    AppointmentViewSet.get_queryset() must not imply write access to a
    colleague's appointment at the same center. Once an appointment is
    COMPLETED or CANCELLED (Appointment.is_locked_for_edit()), only admins
    and center managers may still send a generic update/partial_update to
    it -- the dedicated cancel/complete/reschedule actions enforce their own
    status-transition rules (and surface a 400, not a 403) so the lock only
    applies to the plain edit path, not those actions.
    """

    allowed_roles = (
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.CENTER_MANAGER,
        User.Role.ADMIN,
    )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if not is_owner_doctor(request.user, obj):
            return False
        if (
            getattr(view, "action", None) in ("update", "partial_update")
            and obj.is_locked_for_edit()
            and not (
                getattr(request.user, "is_admin", False)
                or getattr(request.user, "is_center_manager", False)
            )
        ):
            return False
        return True


class CanCancelAppointment(RoleUnionPermission):
    """Doctors, nurses, receptionists, admins, or center managers
    (admin-equivalent) may cancel an appointment. Was an inline
    `self.permission_denied(...)` check inside AppointmentViewSet.cancel()
    (B7) -- moved to a permission class so it's checked at dispatch() time
    like every other write gate, instead of after get_object()."""

    allowed_roles = (
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.ADMIN,
        User.Role.CENTER_MANAGER,
    )


class CanCompleteAppointment(RoleUnionPermission):
    """Doctors, nurses, receptionists, admins, or center managers
    (admin-equivalent) may complete an appointment; a doctor may only
    complete their own (mirrors CanManageAppointments' object-level check --
    was previously enforced there since AppointmentViewSet.complete() ran
    through write_permission_classes=[CanManageAppointments] on top of its
    own inline role check)."""

    allowed_roles = (
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.ADMIN,
        User.Role.CENTER_MANAGER,
    )

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


class CanSendStaffEmail(RoleUnionPermission):
    """Comunicaciones (apps.communications): only Admin/Doctor may compose a
    staff email (Nurse/Receptionist/IT cannot). Whether the message may use
    kind=ALERTA/priority=ALERTA (Admin-only) is enforced in
    MessageSerializer.validate(), not here -- that's a field-level rule this
    method-wide permission class can't express."""

    allowed_roles = (User.Role.ADMIN, User.Role.DOCTOR)


class CanSendManualReminder(RoleUnionPermission):
    """Comunicaciones: manual 'Enviar recordatorio WhatsApp' on an
    appointment -- same role set as CanCancelAppointment."""

    allowed_roles = (
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.ADMIN,
        User.Role.CENTER_MANAGER,
    )


class CanManageRecetas(RoleUnionPermission):
    """Recetas médicas: only Admin/Doctor may create/update/emitir/duplicar
    (Nurse can view -- see IsAdminDoctorOrNurse on RecetaViewSet's read side
    -- but not write), same role set as CanSendStaffEmail
    (RECETAS_REQUIREMENTS.md §10).

    Object-level (update/partial_update/destroy only -- emitir/anular/
    duplicar/guardar_cambios all enforce their own inline object-level rules
    in RecetaViewSet, since none of them share this same "BORRADOR-only"
    shape): only the receta's médico or its creator may reach the generic
    write path, and only while it's still BORRADOR -- once EMITIDA, líneas
    may only change through the dedicated `guardar_cambios` action (the
    1-hour edit window), and ANULADA is terminal. Admins bypass both the
    ownership and status checks."""

    allowed_roles = (User.Role.ADMIN, User.Role.DOCTOR)

    def has_object_permission(self, request, view, obj):
        if getattr(view, "action", None) not in ("update", "partial_update", "destroy"):
            return True
        if getattr(request.user, "is_admin", False):
            return True
        is_owner = obj.medico.user_id == request.user.id or obj.created_by_id == request.user.id
        return is_owner and not obj.is_locked_for_edit()


class IsReportesViewer(RoleUnionPermission):
    """Reportes page + Generar: TI/Admin (any center) and Gerente de centro
    (own center only -- enforced in the view, not here, since it's an
    object/param-level scope, not a role gate)."""

    allowed_roles = (User.Role.ADMIN, User.Role.IT, User.Role.CENTER_MANAGER)


class IsReportesEditor(RoleUnionPermission):
    """Create/edit/deactivate report and pack definitions: TI/Admin only --
    Gerente de centro may generate but not author definitions."""

    allowed_roles = (User.Role.ADMIN, User.Role.IT)


class PatientDataPermission(BasePermission):
    """
    Patient data is sensitive: writes require Admin/Doctor/Receptionist/Nurse/
    CenterManager (admin-equivalent); reads are allowed for authenticated
    staff only, and doctors/admins/center managers see full records while
    others see redacted summaries (enforced by serializers).
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
            or request.user.is_nurse
            or request.user.is_center_manager
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return is_staff_role(request.user)
        return (
            request.user.is_admin
            or request.user.is_doctor
            or request.user.is_receptionist
            or request.user.is_nurse
            or request.user.is_center_manager
        )
