"""Throttle classes reading their rate from the runtime-configurable
SystemSettings singleton instead of the static DEFAULT_THROTTLE_RATES dict.

``get_rate()`` is called per-request by DRF's throttling machinery, so this
picks up an admin's rate-limit change immediately (bounded by the ~60s
cache TTL backstop) without a process restart."""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from apps.systemsettings.services import get_settings


class SettingsAnonRateThrottle(AnonRateThrottle):
    def get_rate(self):
        return f"{get_settings().anon_rate_limit_per_min}/min"


class SettingsUserRateThrottle(UserRateThrottle):
    def get_rate(self):
        return f"{get_settings().user_rate_limit_per_min}/min"


class SettingsLoginRateThrottle(AnonRateThrottle):
    """Scoped throttle for the login endpoint (``LoginView``) -- kept
    separate from ``SettingsAnonRateThrottle`` since login attempts are
    rate-limited far more tightly than general anonymous traffic."""

    scope = "login"

    def get_rate(self):
        return f"{get_settings().login_rate_limit_per_min}/min"
