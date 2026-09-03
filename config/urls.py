from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularSwaggerView

from apps.core.views import CachedSpectacularAPIView
from apps.records.views import ProtectedMediaView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.centers.urls")),
    path("api/", include("apps.ars.urls")),
    path("api/", include("apps.doctors.urls")),
    path("api/", include("apps.patients.urls")),
    path("api/", include("apps.records.urls")),
    path("api/", include("apps.medicines.urls")),
    path("api/", include("apps.prescriptions.urls")),
    path("api/", include("apps.appointments.urls")),
    path("api/", include("apps.services.urls")),
    path("api/", include("apps.rooms.urls")),
    path("api/", include("apps.encounters.urls")),
    path("api/", include("apps.systemsettings.urls")),
    path("api/", include("apps.communications.urls")),
    path("api/", include("apps.reportes.urls")),
    path("api/health/", lambda request: JsonResponse({"status": "ok"}), name="health"),
    path("api/schema/", CachedSpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Media is served through a signed-token endpoint (no unauthenticated
    # static serving of /media/).
    path("media/<path:file_path>", ProtectedMediaView.as_view(), name="protected_media"),
]
