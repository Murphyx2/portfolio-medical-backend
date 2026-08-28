from django.utils import timezone
from rest_framework import serializers

from apps.appointments.models import Appointment
from apps.centers.models import MedicalCenter
from apps.core.masking import apply_masking
from apps.core.serializers import CoreModelSerializer, full_name_or_username
from apps.core.services import is_own_doctor_relation
from apps.doctors.serializers import DoctorLiteSerializer as _DoctorLiteBase
from apps.patients.serializers import PatientSummarySerializer
from apps.services.serializers import ServiceLiteSerializer


class PatientLiteSerializer(PatientSummarySerializer):
    # Masked subset (see AppointmentSerializer's
    # apply_masking(masked_nested=(("patient_info", (...)),)) below):
    # full_name/phone. `phone` powers the Appointments table's "patient
    # phone" column -- the primary scalar phone, not extra_phones.
    phone = serializers.CharField(read_only=True)
    # Drives the "Enviar recordatorio WhatsApp" button's enabled/disabled
    # state on the appointment detail view (apps.communications) -- not PII
    # content itself, just a consent flag, so it isn't in the masked subset.
    whatsapp_opt_in = serializers.BooleanField(read_only=True)

    class Meta(PatientSummarySerializer.Meta):
        fields = ["id", "full_name", "gender", "phone", "whatsapp_opt_in"]


class DoctorLiteSerializer(_DoctorLiteBase):
    class Meta(_DoctorLiteBase.Meta):
        fields = ["id", "full_name"]


class AppointmentSerializer(CoreModelSerializer):
    patient_info = PatientLiteSerializer(source="patient", read_only=True)
    doctor_info = DoctorLiteSerializer(source="doctor", read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True, default=None)
    service_detail = ServiceLiteSerializer(source="service", read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "patient_info",
            "doctor",
            "doctor_info",
            "center",
            "center_name",
            "service",
            "service_detail",
            "date_time",
            "duration_minutes",
            "status",
            "notes",
            "cancel_reason",
            "created_by",
            "created_by_name",
            "created_at",
            "active",
        ]
        read_only_fields = ["id", "created_by", "created_at", "cancel_reason"]

    def get_fields(self):
        fields = super().get_fields()
        # `service`/`center` stay nullable at the model/DB level (existing
        # rows, safe migration), but every new write from the current form
        # always supplies a service, and center is auto-defaulted in
        # validate() below rather than required from the client.
        fields["service"].required = True
        fields["service"].allow_null = False
        fields["center"].required = False
        return fields

    def get_created_by_name(self, obj):
        return full_name_or_username(obj.created_by)

    def validate_doctor(self, value):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user and user.is_authenticated and not is_own_doctor_relation(user, value):
            raise serializers.ValidationError(
                "Doctors may only manage appointments for themselves."
            )
        return value

    def validate_date_time(self, value):
        # Only reject when the submitted value actually changes the
        # date/time -- editing notes/doctor/service on an appointment
        # that's already past (but still open, e.g. inside the no-show
        # grace window) must keep working.
        if self.instance is not None and self.instance.date_time == value:
            return value
        if value < timezone.now():
            raise serializers.ValidationError("Appointment date/time cannot be in the past.")
        return value

    def validate(self, attrs):
        # center is never collected from the New/Edit Appointment form --
        # always auto-filled from the org's default center when omitted,
        # mirroring PatientFormModal's own is_default autofill.
        if "center" not in attrs or attrs.get("center") is None:
            if self.instance is None or self.instance.center_id is None:
                attrs["center"] = MedicalCenter.objects.filter(is_default=True).first()
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        return apply_masking(
            data,
            self._request_user(),
            masked_fields=("created_by_name", "notes"),
            masked_nested=(("patient_info", ("full_name", "phone")),),
        )
