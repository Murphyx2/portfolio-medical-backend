from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
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
                "refresh": str(refresh),
                "user": user,
            }
        ).data
        return Response(data, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class LogoutView(APIView):
    """Revoke the presented refresh token so it can no longer be replayed."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
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
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserViewSet(AuditMixin, viewsets.ModelViewSet):
    """Admin/IT manage system users and roles."""

    queryset = User.objects.all().order_by("username")
    permission_classes = [IsAdminOrIT]

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
