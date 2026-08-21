from apps.core.permissions import CanManageRooms, IsAdminOrIT
from apps.core.viewsets import ReferenceDataViewSet
from apps.rooms.models import Room, RoomType
from apps.rooms.serializers import RoomSerializer, RoomTypeSerializer


class RoomTypeViewSet(ReferenceDataViewSet):
    queryset = RoomType.all_objects.all()
    serializer_class = RoomTypeSerializer
    write_permission_classes = [CanManageRooms]
    delete_permission_classes = [IsAdminOrIT]
    search_fields = ["name"]
    ordering_fields = ["name"]


class RoomViewSet(ReferenceDataViewSet):
    queryset = Room.all_objects.select_related("center", "room_type").all()
    serializer_class = RoomSerializer
    write_permission_classes = [CanManageRooms]
    delete_permission_classes = [IsAdminOrIT]
    filterset_fields = ["room_type", "center", "active"]
    search_fields = ["code", "name", "floor_area", "notes"]
    ordering_fields = ["code", "name", "room_type__name", "floor_area", "capacity", "center__name"]
