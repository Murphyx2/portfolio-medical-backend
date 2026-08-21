from apps.ars.models import ARS
from apps.ars.serializers import ARSSerializer
from apps.core.permissions import IsAdmin
from apps.core.viewsets import ReferenceDataViewSet


class ARSViewSet(ReferenceDataViewSet):
    queryset = ARS.all_objects.prefetch_related("programs")
    serializer_class = ARSSerializer
    write_permission_classes = [IsAdmin]
    filterset_fields = ["name"]
    search_fields = ["ars_id", "name"]
    ordering_fields = ["ars_id", "name"]
