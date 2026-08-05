from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.ars.views import ARSViewSet

router = DefaultRouter()
router.register("ars", ARSViewSet, basename="ars")

urlpatterns = [
    path("", include(router.urls)),
]
