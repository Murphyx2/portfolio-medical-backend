import io

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from apps.ars.models import ARS, ARSProgram
from apps.centers.models import MedicalCenter
from apps.core.models import AuditLog
from apps.core.permissions import IsReportesEditor, IsReportesViewer
from apps.core.services import client_ip, log_audit
from apps.reportes.models import ReportDefinition, ReportPack
from apps.reportes.serializers import (
    GeneratePackSerializer,
    GenerateReportSerializer,
    ReportDefinitionSerializer,
    ReportPackSerializer,
)
from apps.reportes.services.engine import ReportTooLargeError, servicios_prestados_rows
from apps.reportes.services.excel import build_individual_filename, build_pack_zip, build_servicios_prestados_workbook


class _ReportesSwapPermissionsMixin:
    """Read + Generar (a POST, but not an authoring action) are open to any
    IsReportesViewer role (admin/it/center_manager); create/update of the
    definition/pack itself is editor-only (admin/it)."""

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS") or self.action == "generar":
            self.permission_classes = [IsReportesViewer]
        else:
            self.permission_classes = [IsReportesEditor]
        return super().get_permissions()


def _resolve_centro_id(request, requested_centro_id):
    """CM callers are locked to their own center regardless of what the
    client sends; Admin/IT may pass any center id or omit for "Todos"."""
    user = request.user
    if user.is_center_manager:
        if user.center_id is None:
            raise ValidationError(
                {"centro": "No tiene un centro asignado. Contacte a un administrador."}
            )
        return user.center_id
    return requested_centro_id


def _parse_mes(mes: str) -> tuple[int, int]:
    year_str, month_str = mes.split("-")
    return int(year_str), int(month_str)


class ReportDefinitionViewSet(_ReportesSwapPermissionsMixin, viewsets.ModelViewSet):
    queryset = ReportDefinition.objects.all()
    serializer_class = ReportDefinitionSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=True, methods=["post"])
    def generar(self, request, pk=None):
        definition = self.get_object()
        if not definition.active:
            raise ValidationError({"detail": "Este reporte esta desactivado."})
        if definition.engine_key != "servicios_prestados":
            raise ValidationError({"detail": "Motor de reporte no soportado."})

        params = GenerateReportSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        year, month = _parse_mes(params.validated_data["mes"])
        centro_id = _resolve_centro_id(request, params.validated_data.get("centro"))
        ars_id = params.validated_data.get("ars")
        programa_id = params.validated_data.get("programa")

        ars = ARS.all_objects.filter(pk=ars_id).first() if ars_id else None
        programa = ARSProgram.all_objects.filter(pk=programa_id).first() if programa_id else None
        centro = MedicalCenter.all_objects.filter(pk=centro_id).first() if centro_id else None

        try:
            rows = servicios_prestados_rows(
                year=year, month=month, ars_id=ars_id, programa_id=programa_id, centro_id=centro_id
            )
        except ReportTooLargeError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        from apps.reportes.services.engine import ars_program_label

        label = ars_program_label(ars, programa)
        wb = build_servicios_prestados_workbook(
            rows=rows,
            label=label,
            year=year,
            month=month,
            centro_name=centro.name if centro else None,
            user=request.user,
        )
        filename = build_individual_filename(ars=ars, programa=programa, year=year, month=month)

        buffer = io.BytesIO()
        wb.save(buffer)

        definition.last_generated_at = timezone.now()
        definition.save(update_fields=["last_generated_at"])
        log_audit(
            user=request.user,
            action=AuditLog.Action.EXPORT,
            target=definition,
            ip_address=client_ip(request),
            details={"mes": params.validated_data["mes"], "ars": ars_id, "programa": programa_id, "centro": centro_id},
        )

        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ReportPackViewSet(_ReportesSwapPermissionsMixin, viewsets.ModelViewSet):
    queryset = ReportPack.objects.all()
    serializer_class = ReportPackSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=True, methods=["post"])
    def generar(self, request, pk=None):
        pack = self.get_object()
        if not pack.active:
            raise ValidationError({"detail": "Este paquete esta desactivado."})
        if pack.engine_key != "paquete_ars":
            raise ValidationError({"detail": "Motor de paquete no soportado."})

        params = GeneratePackSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        year, month = _parse_mes(params.validated_data["mes"])
        centro_id = _resolve_centro_id(request, params.validated_data.get("centro"))
        centro = MedicalCenter.all_objects.filter(pk=centro_id).first() if centro_id else None

        try:
            zip_bytes = build_pack_zip(
                year=year, month=month, centro_id=centro_id, centro_name=centro.name if centro else None, user=request.user
            )
        except ReportTooLargeError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        pack.last_generated_at = timezone.now()
        pack.save(update_fields=["last_generated_at"])
        log_audit(
            user=request.user,
            action=AuditLog.Action.EXPORT,
            target=pack,
            ip_address=client_ip(request),
            details={"mes": params.validated_data["mes"], "centro": centro_id},
        )

        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="paquete_ars_{year:04d}-{month:02d}.zip"'
        return response
