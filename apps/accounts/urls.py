from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    CookieTokenRefreshView,
    LoginView,
    LogoutView,
    MeView,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("token/refresh/", CookieTokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="me"),
    path("", include(router.urls)),
]
