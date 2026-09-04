from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.prescriptions.views import RecetaViewSet

router = DefaultRouter()
router.register("recetas", RecetaViewSet, basename="receta")

urlpatterns = [
    path("", include(router.urls)),
]
