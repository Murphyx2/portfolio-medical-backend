"""Shared base for the reference-data viewsets (medicines, rooms, services,
ARS, medical centers): identical role-swapped permissions, filter backends,
and server-side list caching, differing only in queryset/serializer/fields.

Subclasses supply ``queryset``, ``serializer_class``, ``write_permission_classes``,
optionally ``delete_permission_classes``, ``filterset_fields``, ``search_fields``,
and ``ordering_fields``. Do not set ``cache_model`` -- ``CachedListViewMixin``
derives it from ``queryset.model`` (see ``apps/core/caching.py``).
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from apps.core.caching import CachedListViewMixin
from apps.core.mixins import AuditMixin, SwapPermissionsMixin
from apps.core.permissions import IsStaffUser


class ReferenceDataViewSet(
    SwapPermissionsMixin, AuditMixin, CachedListViewMixin, viewsets.ModelViewSet
):
    permission_classes = [IsStaffUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
