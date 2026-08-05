from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.patients.views import PatientViewSet

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")

urlpatterns = [
    path("", include(router.urls)),
]
