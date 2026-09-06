from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.medicines.views import MedicineViewSet

router = DefaultRouter()
router.register("medicines", MedicineViewSet, basename="medicine")

urlpatterns = [
    path("", include(router.urls)),
]
