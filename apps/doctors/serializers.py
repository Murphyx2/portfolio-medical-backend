from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.doctors.models import DoctorProfile, DoctorSchedule


class DoctorProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        write_only=True,
    )

    class Meta:
        model = DoctorProfile
        fields = [
            "id",
            "user",
            "user_id",
            "username",
            "full_name",
            "specialty",
            "license_number",
            "contact_phone",
            "contact_email",
            "bio",
        ]


class DoctorScheduleSerializer(serializers.ModelSerializer):
    doctor_full_name = serializers.CharField(source="doctor.full_name", read_only=True)
    center_name = serializers.CharField(source="center.name", read_only=True)

    class Meta:
        model = DoctorSchedule
        fields = [
            "id",
            "doctor",
            "doctor_full_name",
            "center",
            "center_name",
            "weekday",
            "weekday_label",
            "start_time",
            "end_time",
        ]
        read_only_fields = ["weekday_label"]

    weekday_label = serializers.SerializerMethodField()

    def get_weekday_label(self, obj):
        return obj.get_weekday_display()
