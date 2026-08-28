from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.records.views import (
    APCategoryViewSet,
    APTypeViewSet,
    MedicalRecordViewSet,
    RecordEntryViewSet,
    RecordFamilyConditionViewSet,
    RecordImageViewSet,
    RecordPersonalConditionViewSet,
    upload_limits,
)

router = DefaultRouter()
router.register("medical-records", MedicalRecordViewSet, basename="medicalrecord")
router.register("record-entries", RecordEntryViewSet, basename="recordentry")
router.register("personal-conditions", RecordPersonalConditionViewSet, basename="recordpersonalcondition")
router.register("family-conditions", RecordFamilyConditionViewSet, basename="recordfamilycondition")
router.register("images", RecordImageViewSet, basename="recordimage")
router.register("ap-categories", APCategoryViewSet, basename="apcategory")
router.register("ap-types", APTypeViewSet, basename="aptype")

urlpatterns = [
    path("records/upload-limits/", upload_limits, name="record-upload-limits"),
    path("", include(router.urls)),
]
