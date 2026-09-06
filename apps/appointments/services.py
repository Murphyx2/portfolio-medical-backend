"""Service-layer functions for the appointments app, callable from other
apps without those apps reaching into apps.appointments.models directly (the
modular-monolith convention: cross-app writes go through a service/serializer
call, not a raw model import)."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.core.services import client_ip, log_audit

NO_SHOW_REASON = "Paciente no se presento a consulta."
NO_SHOW_GRACE = timedelta(hours=12)


def check_slot_available(doctor, date_time, duration_minutes, *, exclude_pk=None) -> bool:
    """True when `doctor` has no SCHEDULED/CONFIRMED appointment overlapping
    [date_time, date_time+duration_minutes) -- shared by
    AppointmentSerializer.validate() and Receta.emitir's optional "Crear
    cita" step (RECETAS_REQUIREMENTS.md §7), so both paths enforce the same
    "Ya existe una cita en ese horario" rule. CANCELLED/NO_SHOW/COMPLETED
    appointments never occupy a slot. `exclude_pk` lets an edit compare
    against every appointment except itself.

    duration_minutes varies per row, so an exact DB-side range comparison
    would need backend-specific interval arithmetic (Postgres vs the
    SQLite test backend) -- instead this narrows to a plausible window
    (a doctor's day-schedule is always small) and does the exact overlap
    check in Python.
    """
    new_start = date_time
    new_end = date_time + timedelta(minutes=duration_minutes)
    candidates = Appointment.objects.filter(
        doctor=doctor,
        status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
        date_time__lt=new_end,
        date_time__gt=new_start - timedelta(hours=24),
    )
    if exclude_pk is not None:
        candidates = candidates.exclude(pk=exclude_pk)
    for appt in candidates:
        existing_end = appt.date_time + timedelta(minutes=appt.duration_minutes)
        if appt.date_time < new_end and existing_end > new_start:
            return False
    return True


def create_appointment(*, patient, doctor, center, service, date_time, created_by) -> Appointment:
    """Thin wrapper so cross-app callers (apps.prescriptions.views'
    Receta.emitir "Crear cita" step) create an Appointment through a service
    call rather than importing the model directly -- the modular-monolith
    convention this module's docstring describes. Status always starts
    SCHEDULED, same as every other "new appointment" entry point."""
    return Appointment.objects.create(
        patient=patient,
        doctor=doctor,
        center=center,
        service=service,
        date_time=date_time,
        status=Appointment.Status.SCHEDULED,
        created_by=created_by,
    )


def complete_todays_appointments_for_patient(patient, on_date, user, *, request=None) -> list[Appointment]:
    """Called when a patient is admitted (Encounter DRAFT -> ACTIVE): any of
    their SCHEDULED/CONFIRMED appointments dated `on_date` are auto-completed,
    since the admission itself is evidence the patient showed up.
    """
    matches = list(
        Appointment.objects.filter(
            patient=patient,
            status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
            date_time__date=on_date,
        )
    )
    if not matches:
        return []
    with transaction.atomic():
        Appointment.objects.filter(pk__in=[appt.pk for appt in matches]).update(
            status=Appointment.Status.COMPLETED
        )
        for appt in matches:
            appt.status = Appointment.Status.COMPLETED
            log_audit(
                user=user,
                action="UPDATE",
                target=appt,
                ip_address=client_ip(request) if request else None,
                details={"status": "COMPLETED", "reason": "auto_complete_on_admission"},
            )
    return matches


def cancel_noshow_appointments(user, *, request=None) -> list[Appointment]:
    """Lazy maintenance step run on every appointments list/retrieve: any
    SCHEDULED appointment more than NO_SHOW_GRACE past its date_time is
    treated as a no-show and auto-cancelled. Attributed to the requesting
    user since it's a side effect of their read, not a background job (this
    repo has no celery/cron infrastructure).
    """
    cutoff = timezone.now() - NO_SHOW_GRACE
    stale = list(
        Appointment.objects.filter(status=Appointment.Status.SCHEDULED, date_time__lte=cutoff)
    )
    if not stale:
        return []
    with transaction.atomic():
        Appointment.objects.filter(pk__in=[appt.pk for appt in stale]).update(
            status=Appointment.Status.CANCELLED, cancel_reason=NO_SHOW_REASON
        )
        for appt in stale:
            appt.status = Appointment.Status.CANCELLED
            appt.cancel_reason = NO_SHOW_REASON
            log_audit(
                user=user,
                action="UPDATE",
                target=appt,
                ip_address=client_ip(request) if request else None,
                details={"status": "CANCELLED", "reason": NO_SHOW_REASON},
            )
    return stale
