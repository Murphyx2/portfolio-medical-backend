from django.core.signing import BadSignature, TimestampSigner

# How long a signed media URL stays valid (seconds).
MEDIA_TOKEN_MAX_AGE = 60 * 60


def sign_media_token(file_path: str) -> str:
    """Short-lived signed token for an authenticated media URL."""
    return TimestampSigner().sign(file_path)


def verify_media_token(file_path: str, token: str, max_age: int = MEDIA_TOKEN_MAX_AGE) -> bool:
    try:
        return TimestampSigner().unsign(token, max_age=max_age) == file_path
    except BadSignature:
        return False
