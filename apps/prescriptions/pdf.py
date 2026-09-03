"""PDF generation for Receta médica -- WeasyPrint renders
``templates/prescriptions/receta_pdf.html`` into bytes, matching the printed
letterhead structure in RECETAS_REQUIREMENTS.md §8 / Receta_Sample.png.
Called once, at emitir time, against already-snapshotted RecetaLinea rows
(the ViewSet's ``pdf`` action streams this stored file back unchanged
afterwards -- never regenerated from live catalog data)."""

import base64

from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.serializers import full_name_or_username
from apps.patients.models import patient_age

# Imported lazily inside generate_receta_pdf() rather than at module level:
# WeasyPrint dlopen()s Pango/Cairo/GObject at import time (see the backend
# Dockerfile's apt-get libs), so importing it eagerly here would make every
# view in this module fail to load -- not just the PDF action -- on any
# environment missing those system libraries (e.g. a bare Windows dev
# sandbox with no GTK stack installed).


def _logo_data_uri(centro) -> str | None:
    """Inlined as a data: URI so the standalone HTML string WeasyPrint
    renders never needs a base_url/filesystem lookup for MEDIA_ROOT --
    returns None (§3: "If empty, skip logo") when there's no file, or the
    file on disk has gone missing."""
    if not centro.logo:
        return None
    try:
        with centro.logo.open("rb") as fh:
            data = fh.read()
    except (FileNotFoundError, ValueError):
        return None
    ext = (centro.logo.name.rsplit(".", 1)[-1] or "png").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _build_context(receta) -> dict:
    centro = receta.centro
    patient = receta.patient
    # Repeatable phones/emails win when present; fall back to the legacy
    # single fields for a center created before (or never touched by) the
    # 0008 backfill migration -- either way this must not crash on an empty
    # list (§3).
    phones = [p.number for p in centro.phones.all()] or (
        [centro.phone] if centro.phone else []
    )
    emails = [e.email for e in centro.emails.all()] or (
        [centro.email] if centro.email else []
    )
    lineas = [
        {
            "nombre_impreso": linea.nombre_impreso,
            "concentracion_valor": linea.concentracion_valor,
            "unidad": linea.unidad,
            "cantidad": linea.cantidad,
            "dosis_texto": linea.dosis_texto,
            "via": linea.via,
        }
        for linea in receta.lineas.all()
    ]
    return {
        "centro": {
            "logo_data_uri": _logo_data_uri(centro),
            "nombre_legal": centro.nombre_legal or centro.name,
            "nombre_corto": centro.nombre_corto,
            "rnc": centro.rnc,
            "address": centro.address,
            "phones": phones,
            "emails": emails,
        },
        "lineas": lineas,
        "paciente": {
            "full_name": patient.full_name,
            "edad": patient_age(patient),
            # The PDF is always Spanish regardless of the staff member's UI
            # language (requirements §12), so Patient.Gender's own (English)
            # choice labels can't be used directly here.
            "sexo": {"MALE": "Masculino", "FEMALE": "Femenino"}.get(patient.gender, patient.gender),
        },
        "fecha": receta.fecha,
        "proxima_cita_at": receta.proxima_cita_at,
        "generado_por": full_name_or_username(receta.created_by) if receta.created_by_id else "",
        "impreso_en": timezone.now(),
    }


def generate_receta_pdf(receta) -> bytes:
    from weasyprint import HTML

    context = _build_context(receta)
    # Two-pass render: WeasyPrint's `@page { counter(pages) }` rule in the
    # template already prints a correct running "Página X de Y" in the page
    # margin on every physical page -- this first pass exists only to learn
    # the total page count so the footer BOX's own "Página 1 de N" line
    # (ordinary document flow, which CSS page counters can't reach) shows a
    # real N instead of a hardcoded 1. Best-effort for the multi-page case
    # (§8 expects "one page when few lines" as the common case): every
    # physical page's box would then read "Página 1 de N" while the
    # page-corner margin box still numbers each page correctly.
    html = render_to_string(
        "prescriptions/receta_pdf.html", {**context, "pagina_total": 1}
    )
    total_pages = len(HTML(string=html).render().pages)
    html = render_to_string(
        "prescriptions/receta_pdf.html", {**context, "pagina_total": total_pages}
    )
    return HTML(string=html).write_pdf()
