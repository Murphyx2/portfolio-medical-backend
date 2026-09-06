from django.urls import path

from apps.systemsettings.views import SystemSettingsView, reset_settings

urlpatterns = [
    path("settings/", SystemSettingsView.as_view(), name="system-settings"),
    path("settings/reset/", reset_settings, name="system-settings-reset"),
]
