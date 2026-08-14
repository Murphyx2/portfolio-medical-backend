from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.encounters.views import EncounterTypeViewSet, EncounterViewSet

router = DefaultRouter()
router.register("encounters", EncounterViewSet, basename="encounter")
router.register("encounter-types", EncounterTypeViewSet, basename="encounter-type")

urlpatterns = [
    path("", include(router.urls)),
]
