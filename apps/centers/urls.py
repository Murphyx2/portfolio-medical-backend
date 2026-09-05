from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.centers.views import DoctorCenterBindingViewSet, MedicalCenterViewSet

router = DefaultRouter()
router.register("centers", MedicalCenterViewSet, basename="medicalcenter")
router.register("bindings", DoctorCenterBindingViewSet, basename="doctorcenterbinding")

urlpatterns = [
    path("", include(router.urls)),
]
