from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.services.views import ServicePriceViewSet, ServiceTypeViewSet, ServiceViewSet

router = DefaultRouter()
router.register("services", ServiceViewSet, basename="service")
router.register("service-types", ServiceTypeViewSet, basename="servicetype")
router.register("service-prices", ServicePriceViewSet, basename="serviceprice")

urlpatterns = [
    path("", include(router.urls)),
]
