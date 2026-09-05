from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from apps.accounts.models import User
from apps.appointments.services import check_slot_available, create_appointment
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import CanManageRecetas, IsAdminDoctorOrNurse
from apps.core.services import scope_queryset
from apps.medicines.models import Medicine
from apps.prescriptions.models import Receta, RecetaLinea
from apps.prescriptions.pdf import generate_receta_pdf
from apps.prescriptions.serializers import RecetaLineaSerializer, RecetaSerializer
from apps.records.models import MedicalRecord, RecordImage
from apps.services.models import Service

# Default appointment length for the "Crear cita" step on emitir -- there's
# no per-service duration on the Receta form (§7), so this mirrors
# Appointment.duration_minutes' own model default.
DEFAULT_CITA_DURATION_MINUTES = 30


class RecetaViewSet(SwapPermissionsMixin, AuditMixin, viewsets.ModelViewSet):
    # Read (list/retrieve/pdf) is open to anyone who can open the expediente
    # (§10: Admin/Doctor/Nurse/CenterManager), further scoped by center/
    # ownership below via get_queryset(); writes -- including the
    # emitir/duplicar business actions -- are Admin/Doctor only. `anular`
    # narrows further still (author-or-admin) via its own object-level check
    # below, since CanManageRecetas alone can't express "only the author".
    #
    # Deliberately NOT a ReferenceDataViewSet/CachedListViewMixin: Receta
    # carries a patient FK (PHI), and apps.core.caching's server-side list
    # cache is reserved for non-PHI reference data only (see its module
    # docstring) -- caching this would risk serving one patient's
    # prescriptions to another requester.
    permission_classes = [IsAdminDoctorOrNurse]
    write_permission_classes = [CanManageRecetas]
    queryset = Receta.all_objects.select_related(
        "patient", "centro", "medico", "created_by"
    ).prefetch_related("lineas")
    serializer_class = RecetaSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["patient", "centro", "medico", "estado"]
    ordering_fields = ["fecha", "created_at"]

    def get_queryset(self):
        # Same scoping every other clinical resource (Records/Appointments/
        # Encounters) already applies: a doctor sees recetas at their
        # approved centers, plus any they personally prescribed, even
        # centerless; non-doctor staff (Admin/Nurse) are center-agnostic
        # per this app's existing role model, unchanged. Covers every
        # action here (retrieve/pdf/emitir/guardar_cambios/anular/duplicar
        # all resolve through get_object() -> this queryset), not just list.
        return scope_queryset(
            super().get_queryset(), self.request.user,
            center_field="centro", owner_field="medico__user",
        )

    def perform_create(self, serializer):
        self.perform_create_with_owner(serializer, "created_by")

    # emitir/anular/duplicar are all POST -- SwapPermissionsMixin's
    # method-keyed swap already lands every one of them on
    # write_permission_classes (CanManageRecetas) with no override needed
    # here. anular additionally enforces its own object-level
    # author-or-admin rule inline (below), since CanManageRecetas alone
    # can't express "only the author" -- that check has to run after
    # get_object(), like AuditMixin.restore's admin-only check.

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def emitir(self, request, pk=None):
        """BORRADOR -> EMITIDA: validate, snapshot catalog values onto each
        línea, optionally create the "próxima cita" appointment, render and
        store the PDF, and attach it to the patient's expediente -- all in
        one transaction so a slot conflict or PDF failure leaves nothing
        behind (RECETAS_REQUIREMENTS.md §7-9)."""
        receta = self.get_object()
        if receta.estado != Receta.Estado.BORRADOR:
            raise serializers.ValidationError(
                {"detail": "Solo una receta en Borrador puede emitirse."}
            )
        lineas = list(receta.lineas.all())
        if not any(l.nombre_impreso and l.cantidad and l.dosis_texto for l in lineas):
            raise serializers.ValidationError(
                {"lineas": "Se requiere al menos una línea con nombre, cantidad y dosis."}
            )

        # Optional "Crear cita en el calendario" step -- validated BEFORE
        # anything is written (§7: block with "Ya existe una cita en ese
        # horario" the same way Nueva cita does) so emitir stays atomic:
        # either everything below succeeds, or nothing changes.
        crear_cita = bool(request.data.get("crear_cita"))
        if crear_cita:
            proxima_cita_at = request.data.get("proxima_cita_at") or receta.proxima_cita_at
            servicio_id = request.data.get("servicio")
            if not proxima_cita_at or not servicio_id:
                raise serializers.ValidationError(
                    {"crear_cita": "Próxima cita y servicio son requeridos."}
                )
            proxima_cita_dt = proxima_cita_at
            if isinstance(proxima_cita_dt, str):
                proxima_cita_dt = parse_datetime(proxima_cita_dt)
            if proxima_cita_dt is None:
                raise serializers.ValidationError({"proxima_cita_at": "Fecha inválida."})
            # The frontend sends a plain datetime-local string with no
            # timezone offset, so parse_datetime() returns it naive --
            # unlike AppointmentSerializer's DateTimeField, which
            # auto-localizes naive input on deserialization, this manual
            # parse skips that step and would otherwise crash comparing
            # against aware Appointment.date_time values below.
            if timezone.is_naive(proxima_cita_dt):
                proxima_cita_dt = timezone.make_aware(proxima_cita_dt)
            try:
                servicio = Service.objects.get(pk=servicio_id)
            except Service.DoesNotExist:
                raise serializers.ValidationError({"servicio": "Servicio inválido."})
            if not check_slot_available(
                receta.medico, proxima_cita_dt, DEFAULT_CITA_DURATION_MINUTES
            ):
                raise serializers.ValidationError(
                    {"proxima_cita_at": "Ya existe una cita en ese horario"}
                )
            receta.proxima_cita_at = proxima_cita_dt

        # Snapshot §8: refresh nombre_impreso/concentracion_valor/unidad/via
        # from the *live* Medicine row at this instant, regardless of what
        # the client already sent -- "snapshot at emit time" is the actual
        # guarantee, not "trust the client".
        medicamento_ids = [l.medicamento_id for l in lineas if l.medicamento_id]
        medicines = Medicine.objects.in_bulk(medicamento_ids)
        for linea in lineas:
            medicamento = medicines.get(linea.medicamento_id) if linea.medicamento_id else None
            if medicamento is None:
                continue
            linea.nombre_impreso = medicamento.commercial_name or medicamento.generic_name
            linea.concentracion_valor = medicamento.concentracion_valor
            linea.unidad = medicamento.concentracion_unidad
            linea.via = medicamento.via_pred
        RecetaLinea.objects.bulk_update(
            lineas, ["nombre_impreso", "concentracion_valor", "unidad", "via"]
        )

        if crear_cita:
            receta.cita = create_appointment(
                patient=receta.patient,
                doctor=receta.medico,
                center=receta.centro,
                service=servicio,
                date_time=receta.proxima_cita_at,
                created_by=request.user,
            )

        pdf_bytes = generate_receta_pdf(receta)
        receta.pdf.save(f"receta_{receta.pk}.pdf", ContentFile(pdf_bytes), save=False)
        receta.estado = Receta.Estado.EMITIDA
        receta.emitida_at = timezone.now()
        receta.save()

        self._attach_to_expediente(receta)

        self.log_action(
            receta, "UPDATE", details={"estado": "EMITIDA", "crear_cita": crear_cita}
        )
        return Response(self.get_serializer(receta).data)

    def _attach_to_expediente(self, receta, *, previous_pdf_name: str | None = None):
        """§9: attach the generated PDF to the patient's expediente. This
        codebase keeps at most one *active* MedicalRecord per patient
        (uniq_active_medicalrecord_patient) -- mirrors
        RecordImageViewSet.perform_create's plain "attach to this record"
        behavior rather than inventing new expediente lifecycle rules. If a
        patient genuinely has no active record yet, the receta PDF still
        stays on the Receta itself (Ver PDF keeps working); it's just not
        also mirrored onto Archivos.

        `previous_pdf_name` is set when `guardar_cambios` regenerates an
        already-attached PDF in place -- updates that existing Archivos row
        instead of adding a second one for the same receta. Falls through to
        creating a fresh row if no matching one is found (e.g. the record
        was created/changed after the original emitir)."""
        record = MedicalRecord.objects.filter(patient=receta.patient).first()
        if record is None:
            return
        if previous_pdf_name:
            updated = RecordImage.objects.filter(record=record, image=previous_pdf_name).update(
                image=receta.pdf.name,
                caption=f"Receta {receta.fecha:%Y-%m-%d} (editada)",
            )
            if updated:
                return
        # `image=receta.pdf` reuses the already-committed FieldFile's stored
        # name as-is (Django doesn't re-run record_image_upload_to for an
        # already-saved file) -- the receta PDF and the Archivos row point
        # at the same physical file rather than a duplicated copy, which is
        # fine here since neither side ever mutates that file in place.
        RecordImage.objects.create(
            record=record,
            image=receta.pdf,
            caption=f"Receta {receta.fecha:%Y-%m-%d}",
            uploaded_by=receta.created_by,
            kind=RecordImage.Kind.PDF,
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def guardar_cambios(self, request, pk=None):
        """Amends an already-EMITIDA receta's líneas within its 1-hour
        window (Receta.editable_by_within_window) -- lets a doctor fix a
        mistake without a full anular+duplicar. Re-runs the same
        catalog-snapshot step and PDF generation `emitir` does, and replaces
        (rather than duplicates) the existing Expediente/Archivos
        attachment. Only líneas may change here -- patient/centro/médico/
        fecha/estado are untouched, matching the frontend's own scope for
        this action."""
        receta = self.get_object()
        if not receta.editable_by_within_window(request.user):
            self.permission_denied(
                request,
                message="Esta receta ya no puede editarse (fuera de la ventana de 1 hora, o no le pertenece).",
            )

        lineas_serializer = RecetaLineaSerializer(data=request.data.get("lineas", []), many=True)
        lineas_serializer.is_valid(raise_exception=True)
        lineas_data = lineas_serializer.validated_data
        if not any(
            l.get("nombre_impreso") and l.get("cantidad") and l.get("dosis_texto") for l in lineas_data
        ):
            raise serializers.ValidationError(
                {"lineas": "Se requiere al menos una línea con nombre, cantidad y dosis."}
            )

        receta.lineas.all().delete()
        RecetaLinea.objects.bulk_create(RecetaLinea(receta=receta, **linea) for linea in lineas_data)
        lineas = list(receta.lineas.all())

        # Same snapshot-from-catalog step as emitir (§8).
        medicamento_ids = [l.medicamento_id for l in lineas if l.medicamento_id]
        medicines = Medicine.objects.in_bulk(medicamento_ids)
        for linea in lineas:
            medicamento = medicines.get(linea.medicamento_id) if linea.medicamento_id else None
            if medicamento is None:
                continue
            linea.nombre_impreso = medicamento.commercial_name or medicamento.generic_name
            linea.concentracion_valor = medicamento.concentracion_valor
            linea.unidad = medicamento.concentracion_unidad
            linea.via = medicamento.via_pred
        RecetaLinea.objects.bulk_update(
            lineas, ["nombre_impreso", "concentracion_valor", "unidad", "via"]
        )

        previous_pdf_name = receta.pdf.name if receta.pdf else None
        pdf_bytes = generate_receta_pdf(receta)
        receta.pdf.save(f"receta_{receta.pk}.pdf", ContentFile(pdf_bytes), save=False)
        receta.save()

        self._attach_to_expediente(receta, previous_pdf_name=previous_pdf_name)

        self.log_action(receta, "UPDATE", details={"guardar_cambios": True})
        return Response(self.get_serializer(receta).data)

    @action(detail=True, methods=["post"])
    def anular(self, request, pk=None):
        """Soft-delete-as-void (§10): PDF remains for audit -- never
        deleted. Only the receta's author or an Admin may anular."""
        receta = self.get_object()
        if not (receta.created_by_id == request.user.id or request.user.role == User.Role.ADMIN):
            self.permission_denied(
                request, message="Solo el autor o un administrador puede anular esta receta."
            )
        if receta.estado not in (Receta.Estado.BORRADOR, Receta.Estado.EMITIDA):
            raise serializers.ValidationError({"detail": "Esta receta ya está anulada."})
        receta.estado = Receta.Estado.ANULADA
        receta.save(update_fields=["estado"])
        self.log_action(receta, "UPDATE", details={"estado": "ANULADA"})
        return Response(self.get_serializer(receta).data)

    @action(detail=True, methods=["post"])
    def duplicar(self, request, pk=None):
        """Creates a new BORRADOR receta copying patient/centro/medico/
        líneas from `receta` (any estado may be duplicated) -- new fecha,
        no cita, no pdf, per RECETAS_REQUIREMENTS.md §6."""
        receta = self.get_object()
        nueva = Receta.objects.create(
            patient=receta.patient,
            centro=receta.centro,
            medico=receta.medico,
            created_by=request.user,
            fecha=timezone.now(),
            estado=Receta.Estado.BORRADOR,
        )
        RecetaLinea.objects.bulk_create(
            RecetaLinea(
                receta=nueva,
                medicamento_id=linea.medicamento_id,
                nombre_impreso=linea.nombre_impreso,
                cantidad=linea.cantidad,
                concentracion_valor=linea.concentracion_valor,
                unidad=linea.unidad,
                via=linea.via,
                forma=linea.forma,
                fuera_de_catalogo=linea.fuera_de_catalogo,
                dosis_json=linea.dosis_json,
                dosis_texto=linea.dosis_texto,
                indicacion_extra=linea.indicacion_extra,
                uso_continuo=linea.uso_continuo,
                orden=linea.orden,
            )
            for linea in receta.lineas.all()
        )
        self.log_action(nueva, "CREATE", details={"duplicado_de": receta.pk})
        return Response(self.get_serializer(nueva).data, status=201)

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        """Streams the stored PDF snapshot -- never regenerated from live
        catalog data after emitir (§8)."""
        receta = self.get_object()
        if receta.estado == Receta.Estado.BORRADOR or not receta.pdf:
            raise Http404("Esta receta aún no tiene un PDF emitido.")
        return FileResponse(
            receta.pdf.open("rb"), content_type="application/pdf", filename=receta.pdf.name
        )

