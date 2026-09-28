import hashlib
import hmac
import ipaddress
import secrets
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


API_TOKEN_PREFIX = "vp_live_"


class IntegrationSecurityError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedWebhookTarget:
    url: str
    hostname: str
    port: int
    path: str
    addresses: tuple[str, ...]


def generate_api_token():
    key_id = secrets.token_urlsafe(9).replace("-", "").replace("_", "")[:12]
    secret = secrets.token_urlsafe(32)
    prefix = f"{API_TOKEN_PREFIX}{key_id}"
    token = f"{prefix}.{secret}"
    return prefix, token, secret[-4:]


def hash_api_token(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def verify_api_token(token, expected_hash):
    return hmac.compare_digest(hash_api_token(token), str(expected_hash or ""))


def _fernet():
    key = str(current_app.config.get("INTEGRATION_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise IntegrationSecurityError(
            "INTEGRATION_ENCRYPTION_KEY tanimli degil. Fernet.generate_key() ile ayri bir anahtar olusturun."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as error:
        raise IntegrationSecurityError("INTEGRATION_ENCRYPTION_KEY gecerli bir Fernet anahtari degil.") from error


def encrypt_secret(secret):
    return _fernet().encrypt(str(secret).encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext):
    try:
        return _fernet().decrypt(str(ciphertext).encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise IntegrationSecurityError("Webhook sirri cozumlenemedi.") from error


def generate_webhook_secret():
    return secrets.token_urlsafe(32)


def _is_forbidden_address(value):
    address = ipaddress.ip_address(value)
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def resolve_webhook_target(url, *, resolver=socket.getaddrinfo):
    raw = str(url or "").strip()
    if not raw or len(raw) > 1000 or any(ord(char) < 32 for char in raw):
        raise IntegrationSecurityError("Gecerli bir webhook adresi girin.")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise IntegrationSecurityError("Webhook adresi gecersiz.") from error
    if parsed.scheme.lower() != "https":
        raise IntegrationSecurityError("Webhook adresi HTTPS kullanmalidir.")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise IntegrationSecurityError(
            "Webhook adresinde kullanici bilgisi, query veya fragment bulunamaz."
        )
    hostname = (parsed.hostname or "").strip().rstrip(".").lower()
    if not hostname or hostname == "localhost" or hostname.endswith((".local", ".localhost")):
        raise IntegrationSecurityError("Yerel ag webhook hedefleri kullanilamaz.")
    if port not in (None, 443):
        raise IntegrationSecurityError("Webhook icin yalnizca standart HTTPS portu kullanilabilir.")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise IntegrationSecurityError("Webhook adresinde dogrudan IP kullanilamaz.")
    try:
        answers = resolver(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise IntegrationSecurityError("Webhook alan adi cozumlenemedi.") from error
    addresses = {answer[4][0] for answer in answers if answer and answer[4]}
    if not addresses:
        raise IntegrationSecurityError("Webhook alan adi bir IP adresine cozumlenemedi.")
    for address in addresses:
        try:
            if _is_forbidden_address(address):
                raise IntegrationSecurityError("Webhook hedefi ozel veya yerel aga cozumleniyor.")
        except ValueError as error:
            raise IntegrationSecurityError("Webhook DNS cevabi gecersiz.") from error
    path = parsed.path or "/"
    return ResolvedWebhookTarget(
        url=raw,
        hostname=hostname,
        port=443,
        path=path,
        addresses=tuple(sorted(addresses)),
    )


def validate_webhook_url(url, *, resolver=socket.getaddrinfo):
    return resolve_webhook_target(url, resolver=resolver).url


def webhook_signature(secret, timestamp, event_id, body):
    signed = b".".join(
        (
            b"v1",
            str(timestamp).encode("ascii"),
            str(event_id).encode("ascii"),
            body,
        )
    )
    digest = hmac.new(str(secret).encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"v1={digest}"
