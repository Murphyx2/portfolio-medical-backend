from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import SAFE_METHODS

from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin
from apps.core.permissions import CanManageRooms, IsAdminOrIT, IsStaffUser
from apps.rooms.models import Room, RoomType
from apps.rooms.serializers import RoomSerializer, RoomTypeSerializer


class RoomTypeViewSet(AuditMixin, CachedListViewMixin, viewsets.ModelViewSet):
    cache_model = "roomtype"
    queryset = RoomType.all_objects.all()
    serializer_class = RoomTypeSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["name"]

    def get_permissions(self):
        if self.request.method == "DELETE":
            self.permission_classes = [IsAdminOrIT]
        elif self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageRooms]
        return super().get_permissions()


class RoomViewSet(AuditMixin, CachedListViewMixin, viewsets.ModelViewSet):
    cache_model = "room"
    queryset = Room.all_objects.select_related("center", "room_type").all()
    serializer_class = RoomSerializer
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["room_type", "center", "active"]
    search_fields = ["code", "name", "floor_area", "notes"]
    ordering_fields = ["code", "name", "room_type__name", "floor_area", "capacity", "center__name"]

    def get_permissions(self):
        if self.request.method == "DELETE":
            self.permission_classes = [IsAdminOrIT]
        elif self.request.method not in SAFE_METHODS:
            self.permission_classes = [CanManageRooms]
        return super().get_permissions()
