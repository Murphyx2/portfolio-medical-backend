from apps.core.permissions import IsAdminOrCenterManager
from apps.core.viewsets import ReferenceDataViewSet
from apps.services.models import Service, ServiceType
from apps.services.serializers import ServiceSerializer, ServiceTypeSerializer


class ServiceTypeViewSet(ReferenceDataViewSet):
    queryset = ServiceType.all_objects.all()
    serializer_class = ServiceTypeSerializer
    write_permission_classes = [IsAdminOrCenterManager]
    search_fields = ["name"]
    ordering_fields = ["name"]


class ServiceViewSet(ReferenceDataViewSet):
    queryset = Service.all_objects.select_related("type").all()
    serializer_class = ServiceSerializer
    write_permission_classes = [IsAdminOrCenterManager]
    filterset_fields = ["type"]
    search_fields = ["name", "simon"]
    ordering_fields = ["name", "simon", "co_pago", "privado"]
