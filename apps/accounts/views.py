from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.serializers import (
    LoginResponseSerializer,
    LoginSerializer,
    UserCreateSerializer,
    UserSerializer,
)
from apps.core.mixins import AuditMixin
from apps.core.permissions import IsAdminOrIT
from apps.core.services import client_ip, log_audit

User = get_user_model()


def _set_refresh_cookie(response, refresh):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh,
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
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


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            user = None

        if user is None or not user.check_password(password) or not user.is_active:
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
        serializer = TokenRefreshSerializer(
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
    """Admin/IT manage system users and roles."""

    queryset = User.objects.all().order_by("username")
    permission_classes = [IsAdminOrIT]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["username", "email", "first_name", "last_name"]
    ordering_fields = ["username", "first_name", "email", "role", "is_active"]

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
        if instance.is_admin and not request.user.is_admin:
            return Response(
                {"detail": "Only admins can delete admin accounts."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)
