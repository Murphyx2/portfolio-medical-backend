"""Custom SimpleJWT token classes whose lifetime is read live from the
SystemSettings singleton instead of being frozen at import time from the
SIMPLE_JWT settings dict.

``lifetime`` MUST be a ``@property`` here, not a plain class attribute --
SimpleJWT's ``Token.set_exp()`` reads ``self.lifetime`` at the moment a
token is issued/rotated, so a class attribute would freeze whatever value
was in scope when this module was first imported (i.e. the process's
lifetime, defeating the whole point of a runtime-editable setting). A
property is re-evaluated on every access.
"""

from datetime import timedelta

from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import AccessToken as BaseAccessToken
from rest_framework_simplejwt.tokens import RefreshToken as BaseRefreshToken

from apps.systemsettings.services import get_settings


class SettingsAccessToken(BaseAccessToken):
    @property
    def lifetime(self):
        return timedelta(minutes=get_settings().access_token_lifetime_minutes)


class SettingsRefreshToken(BaseRefreshToken):
    access_token_class = SettingsAccessToken

    @property
    def lifetime(self):
        return timedelta(days=get_settings().refresh_token_lifetime_days)


class SettingsTokenRefreshSerializer(TokenRefreshSerializer):
    """TokenRefreshSerializer.token_class defaults to the base RefreshToken
    (fixed lifetime from SIMPLE_JWT at import time) -- override it so a
    rotated access token minted during refresh also gets the live,
    runtime-configurable lifetime."""

    token_class = SettingsRefreshToken
