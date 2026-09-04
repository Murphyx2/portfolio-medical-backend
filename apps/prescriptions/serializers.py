from rest_framework import serializers

from apps.core.serializers import CoreModelSerializer
from apps.core.services import is_own_doctor_relation
from apps.prescriptions.models import Receta, RecetaLinea


class RecetaLineaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecetaLinea
        fields = [
            "id",
            "medicamento",
            "nombre_impreso",
            "cantidad",
            "concentracion_valor",
            "unidad",
            "via",
            "forma",
            "fuera_de_catalogo",
            "dosis_json",
            "dosis_texto",
            "indicacion_extra",
            "uso_continuo",
            "orden",
        ]


class RecetaSerializer(CoreModelSerializer):
    # Write side replaces the full set on every save (delete-and-recreate),
    # mirroring DoctorProfileSerializer.extra_phones/MedicalCenterSerializer.
    # phones -- the established nested-write convention in this codebase.
    lineas = RecetaLineaSerializer(many=True, required=False)

    class Meta:
        model = Receta
        fields = [
            "id",
            "patient",
            "centro",
            "medico",
            "created_by",
            "fecha",
            "proxima_cita_at",
            "cita",
            "estado",
            "pdf",
            "lineas",
            "active",
        ]
        read_only_fields = ["id", "created_by", "pdf"]

    def validate_medico(self, value):
        # Mirrors AppointmentSerializer.validate_doctor/DoctorScheduleSerializer.
        # validate_doctor: a doctor may only prescribe as themselves. The
        # composer UI locks this field for a DOCTOR-role user, but a direct
        # API call must not be able to spoof another doctor's identity.
        user = self._request_user()
        if user and user.is_authenticated and not is_own_doctor_relation(user, value):
            raise serializers.ValidationError(
                "Los doctores solo pueden emitir recetas a su propio nombre."
            )
        return value

    def create(self, validated_data):
        lineas = validated_data.pop("lineas", None)
        receta = super().create(validated_data)
        if lineas:
            RecetaLinea.objects.bulk_create(
                RecetaLinea(receta=receta, **linea) for linea in lineas
            )
        return receta

    def update(self, instance, validated_data):
        lineas = validated_data.pop("lineas", None)
        receta = super().update(instance, validated_data)
        if lineas is not None:
            receta.lineas.all().delete()
            RecetaLinea.objects.bulk_create(
                RecetaLinea(receta=receta, **linea) for linea in lineas
            )
        return receta
