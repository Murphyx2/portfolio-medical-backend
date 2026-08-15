"""Core serializer primitives shared across apps.

One base class owns the two conventions every model serializer repeated by
hand: the request->user seam and the active-field writability rule (only
admins may write ``active``; everyone else sees it read-only). Subclasses
inherit both and drop their private copies.
"""

from rest_framework import serializers

from apps.core.services import can_view_inactive


class CoreModelSerializer(serializers.ModelSerializer):
    """Base for every model serializer.

    Owns:
    - ``_request_user()``: the request->user seam (previously a copy-pasted
      module-level ``_request_user(context)`` in five apps).
    - ``get_fields()``: marks ``active`` read-only unless the requester may
      view inactive rows (``can_view_inactive``). Subclasses that need extra
      ``get_fields`` work call ``super().get_fields()`` first.
    """

    def _request_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None) if request else None

    def get_fields(self):
        fields = super().get_fields()
        if "active" in fields and not can_view_inactive(self._request_user()):
            fields["active"].read_only = True
        return fields
