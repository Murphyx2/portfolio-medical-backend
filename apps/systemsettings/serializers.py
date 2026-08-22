from rest_framework import serializers

from apps.systemsettings.models import SystemSettings
from apps.systemsettings.services import EDITABLE_FIELDS


class SystemSettingsSerializer(serializers.ModelSerializer):
    """Retrieve/partial_update serializer for the singleton row.

    Per-field range validation is already declared on the model
    (MinValueValidator/MaxValueValidator matching SETTINGS_PAGE_PLAN.md
    section 2), and ModelSerializer runs those automatically -- no
    duplicated range checks needed here.
    """

    class Meta:
        model = SystemSettings
        fields = [*EDITABLE_FIELDS, "updated_by", "updated_at"]
        read_only_fields = ["updated_by", "updated_at"]
