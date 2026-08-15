from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.encounters.views import EncounterViewSet

router = DefaultRouter()
router.register("encounters", EncounterViewSet, basename="encounter")

urlpatterns = [
    path("", include(router.urls)),
]
