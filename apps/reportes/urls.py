from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.reportes.views import ReportDefinitionViewSet, ReportPackViewSet

router = DefaultRouter()
router.register("reportes/definiciones", ReportDefinitionViewSet, basename="report-definition")
router.register("reportes/paquetes", ReportPackViewSet, basename="report-pack")

urlpatterns = [
    path("", include(router.urls)),
]
