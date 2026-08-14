from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rooms.views import RoomViewSet

router = DefaultRouter()
router.register("rooms", RoomViewSet, basename="room")

urlpatterns = [
    path("", include(router.urls)),
]
