from ipaddress import ip_address

from flask import current_app, request


def _valid_ip(value):
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return str(ip_address(value))
    except ValueError:
        return None


def _trusted_proxy_ips():
    configured = current_app.config.get("TRUSTED_PROXY_IPS", ("127.0.0.1", "::1"))
    if isinstance(configured, str):
        configured = configured.split(",")
    return {_valid_ip(value) for value in configured} - {None}


def request_client_ip(default="unknown"):
    """Return a non-spoofable client IP when the app is behind a trusted proxy."""
    remote_ip = _valid_ip(request.remote_addr)
    if remote_ip in _trusted_proxy_ips():
        real_ip = _valid_ip(request.headers.get("X-Real-IP"))
        if real_ip:
            return real_ip

        forwarded_chain = request.headers.get("X-Forwarded-For", "").split(",")
        for value in reversed(forwarded_chain):
            forwarded_ip = _valid_ip(value)
            if forwarded_ip:
                return forwarded_ip

    return remote_ip or default
