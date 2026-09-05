from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from apps.accounts.serializers import (
    AdminSetPasswordSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    UserCreateSerializer,
    UserSerializer,
)
from apps.accounts.tokens import SettingsRefreshToken as RefreshToken
from apps.accounts.tokens import SettingsTokenRefreshSerializer
from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdminOrCenterManager, IsAdminOrITOrCenterManager
from apps.core.serializers import AuditLogSerializer
from apps.core.services import client_ip, log_audit, resolve_accessible_center_ids
from apps.core.throttling import SettingsLoginRateThrottle
from apps.systemsettings.services import get_settings

User = get_user_model()


def _set_refresh_cookie(response, refresh):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh,
        # Live value (days -> seconds) so a runtime change to the refresh
        # token lifetime setting is reflected in the cookie's own max_age on
        # the very next login/refresh, not just the JWT's internal exp claim.
        max_age=get_settings().refresh_token_lifetime_days * 86400,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response):
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SettingsLoginRateThrottle]

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            user = None

        if user is not None and user.is_locked:
            log_audit(
                user=user,
                action="FAILED_LOGIN",
                ip_address=client_ip(request),
                details={"username": username, "reason": "locked"},
            )
            return Response(
                {"detail": "Account temporarily locked. Try again later."},
                status=status.HTTP_423_LOCKED,
            )

        if user is None or not user.check_password(password) or not user.is_active:
            if user is not None and user.is_active:
                # Read from the runtime-configurable settings singleton;
                # User.LOCKOUT_THRESHOLD/LOCKOUT_MINUTES remain as the
                # hardcoded fallback baked into get_settings() itself.
                lockout_settings = get_settings()
                threshold = getattr(
                    lockout_settings, "login_lockout_threshold", User.LOCKOUT_THRESHOLD
                )
                lockout_minutes = getattr(
                    lockout_settings, "login_lockout_minutes", User.LOCKOUT_MINUTES
                )
                User.objects.filter(pk=user.pk).update(
                    failed_login_count=F("failed_login_count") + 1
                )
                user.refresh_from_db(fields=["failed_login_count"])
                if user.failed_login_count >= threshold:
                    User.objects.filter(pk=user.pk).update(
                        locked_until=timezone.now() + timedelta(minutes=lockout_minutes)
                    )
            log_audit(
                user=user,
                action="FAILED_LOGIN",
                ip_address=client_ip(request),
                details={"username": username},
            )
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.failed_login_count or user.locked_until:
            User.objects.filter(pk=user.pk).update(
                failed_login_count=0, locked_until=None
            )

        refresh = RefreshToken.for_user(user)
        log_audit(
            user=user,
            action="LOGIN",
            ip_address=client_ip(request),
        )
        data = LoginResponseSerializer(
            {
                "access": str(refresh.access_token),
                "user": user,
            }
        ).data
        response = Response(data, status=status.HTTP_200_OK)
        _set_refresh_cookie(response, str(refresh))
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class CookieTokenRefreshView(APIView):
    """Rotate the refresh token carried in the httpOnly cookie.

    Returns only a fresh access token in the body; the rotated refresh token is
    delivered exclusively via the cookie (H-03: never exposed to JS). SimpleJWT
    blacklists the previous refresh on rotation.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        refresh = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not refresh:
            return Response(
                {"detail": "No refresh token cookie present."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        serializer = SettingsTokenRefreshSerializer(
            data={"refresh": refresh},
            context={"request": request},
        )
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            # SimpleJWT raises a plain TokenError for invalid/blacklisted/
            # expired refreshes; Surface as a 401 API exception.
            raise InvalidToken(exc.args[0]) from exc
        response = Response({"access": serializer.validated_data["access"]})
        new_refresh = serializer.validated_data.get("refresh")
        if new_refresh:
            _set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(APIView):
    """Revoke the refresh token in the cookie so it can no longer be replayed."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if not refresh:
            return Response(
                {"detail": "A refresh token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh)
            token.blacklist()
        except TokenError:
            return Response(
                {"detail": "Invalid or expired refresh token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        log_audit(
            user=request.user,
            action="LOGOUT",
            ip_address=client_ip(request),
        )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_refresh_cookie(response)
        return response


class UserViewSet(AuditMixin, viewsets.ModelViewSet):
    """Admin/IT/CenterManager (CM admin-equivalent) manage system users and
    roles.

    Deactivate/restore, unlock, password-reset, and activity are all
    Admin/CenterManager-only (get_permissions) even though IT keeps
    view/create/edit -- these are more sensitive than editing a profile
    field.
    """

    queryset = User.objects.all().order_by("username")
    permission_classes = [IsAdminOrITOrCenterManager]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["username", "email", "first_name", "last_name"]
    ordering_fields = ["username", "first_name", "email", "role", "is_active"]

    ADMIN_ONLY_ACTIONS = {"destroy", "restore", "unlock", "set_password", "activity"}

    def get_queryset(self):
        qs = super().get_queryset()
        ids = resolve_accessible_center_ids(self.request.user)
        if ids is None:
            return qs
        # A center-scoped staff member (receptionist/nurse/IT/center
        # manager) sees: other staff at their own center or with no center
        # assigned yet (User.center itself), plus doctors approved for
        # their center via DoctorCenterBinding -- doctors don't use
        # User.center, so they'd otherwise vanish from a scoped user list
        # entirely even though front-desk staff need to see their roster.
        return qs.filter(
            Q(center_id__in=ids)
            | Q(center__isnull=True)
            | Q(doctor_profile__center_bindings__center_id__in=ids, doctor_profile__center_bindings__approved=True)
        ).distinct()

    def get_permissions(self):
        if self.action in self.ADMIN_ONLY_ACTIONS:
            self.permission_classes = [IsAdminOrCenterManager]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        return UserSerializer

    @action(detail=False, methods=["get"])
    def roles(self, request):
        choices = [
            {"value": value, "label": label}
            for value, label in User.Role.choices
        ]
        return Response(choices)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_admin and not (request.user.is_admin or request.user.is_center_manager):
            return Response(
                {"detail": "Only admins or center managers can delete admin accounts."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        instance = self.get_object()
        instance.failed_login_count = 0
        instance.locked_until = None
        instance.save(update_fields=["failed_login_count", "locked_until"])
        self.log_action(instance, "UPDATE", details={"action": "unlock"})
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=["post"])
    def set_password(self, request, pk=None):
        instance = self.get_object()
        serializer = AdminSetPasswordSerializer(
            data=request.data, context={"target_user": instance}
        )
        serializer.is_valid(raise_exception=True)
        instance.set_password(serializer.validated_data["password"])
        instance.save(update_fields=["password"])
        self.log_action(instance, "UPDATE", details={"action": "password_reset"})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        instance = self.get_object()
        qs = instance.audit_logs.all().order_by("-created_at")
        page = self.paginate_queryset(qs)
        serializer = AuditLogSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)
