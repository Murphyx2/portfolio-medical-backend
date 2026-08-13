from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.services.views import ServiceTypeViewSet, ServiceViewSet

router = DefaultRouter()
router.register("services", ServiceViewSet, basename="service")
router.register("service-types", ServiceTypeViewSet, basename="servicetype")

urlpatterns = [
    path("", include(router.urls)),
]
