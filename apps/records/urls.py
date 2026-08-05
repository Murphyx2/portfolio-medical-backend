from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.records.views import (
    ConsultationLogViewSet,
    MedicalRecordViewSet,
    RecordImageViewSet,
)

router = DefaultRouter()
router.register("medical-records", MedicalRecordViewSet, basename="medicalrecord")
router.register("consultation-logs", ConsultationLogViewSet, basename="consultationlog")
router.register("images", RecordImageViewSet, basename="recordimage")

urlpatterns = [
    path("", include(router.urls)),
]
