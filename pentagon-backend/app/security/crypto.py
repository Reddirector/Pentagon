from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class EncryptionConfigurationError(Exception):
    """Raised when the server has no usable Fernet key configured."""


class EncryptedKeyError(Exception):
    """Raised when a stored API key cannot be decrypted."""


def _fernet() -> Fernet:
    configured_secret = settings.key_encryption_secret
    if configured_secret is None:
        raise EncryptionConfigurationError

    try:
        return Fernet(configured_secret.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise EncryptionConfigurationError from None


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted_key: str) -> str:
    try:
        return _fernet().decrypt(encrypted_key.encode("ascii")).decode("utf-8")
    except EncryptionConfigurationError:
        raise
    except (InvalidToken, ValueError, UnicodeEncodeError, UnicodeDecodeError):
        raise EncryptedKeyError from None
