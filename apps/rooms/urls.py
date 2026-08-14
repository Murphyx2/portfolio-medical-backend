from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.rooms.views import RoomTypeViewSet, RoomViewSet

router = DefaultRouter()
router.register("rooms", RoomViewSet, basename="room")
router.register("room-types", RoomTypeViewSet, basename="room-type")

urlpatterns = [
    path("", include(router.urls)),
]
