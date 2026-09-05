from apps.core.permissions import CanManageMedicines, IsAdminOrITOrCenterManager
from apps.core.viewsets import ReferenceDataViewSet
from apps.medicines.models import Medicine
from apps.medicines.serializers import MedicineSerializer


class MedicineViewSet(ReferenceDataViewSet):
    queryset = Medicine.all_objects.all()
    serializer_class = MedicineSerializer
    write_permission_classes = [CanManageMedicines]
    delete_permission_classes = [IsAdminOrITOrCenterManager]
    filterset_fields = ["generic_name", "commercial_name"]
    search_fields = ["generic_name", "commercial_name", "concentration", "forma", "via_pred"]
    ordering_fields = ["generic_name", "commercial_name", "concentration"]
