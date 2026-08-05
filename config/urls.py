from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/", include("apps.centers.urls")),
    path("api/", include("apps.doctors.urls")),
    path("api/", include("apps.patients.urls")),
    path("api/", include("apps.records.urls")),
    path("api/", include("apps.medicines.urls")),
    path("api/", include("apps.appointments.urls")),
    path("api/health/", lambda request: JsonResponse({"status": "ok"}), name="health"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
