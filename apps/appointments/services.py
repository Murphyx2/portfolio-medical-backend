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
