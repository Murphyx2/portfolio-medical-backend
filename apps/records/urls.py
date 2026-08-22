from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.records.views import (
    ConsultationLogViewSet,
    MedicalRecordViewSet,
    RecordImageViewSet,
    upload_limits,
)

router = DefaultRouter()
router.register("medical-records", MedicalRecordViewSet, basename="medicalrecord")
router.register("consultation-logs", ConsultationLogViewSet, basename="consultationlog")
router.register("images", RecordImageViewSet, basename="recordimage")

urlpatterns = [
    path("records/upload-limits/", upload_limits, name="record-upload-limits"),
    path("", include(router.urls)),
]
