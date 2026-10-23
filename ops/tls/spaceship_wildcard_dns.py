"""Add the one-time VolkaPortal wildcard A record through Spaceship DNS."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DOMAIN = "volkaportal.com"
TARGET_IP = "94.103.45.122"
API_URL = f"https://spaceship.dev/api/v1/dns/records/{DOMAIN}"


def request(method, key, secret, *, query="", payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        API_URL + query,
        data=body,
        method=method,
        headers={
            "X-Api-Key": key,
            "X-Api-Secret": secret,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=30) as response:
            if response.status == 204:
                return None
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Spaceship DNS API returned HTTP {error.code}") from error


def records(key, secret):
    result = []
    while True:
        page = request("GET", key, secret, query=f"?take=500&skip={len(result)}")
        result.extend(page["items"])
        if len(result) >= page["total"]:
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the DNS record")
    parser.add_argument(
        "--key-file", type=Path, default=Path("/etc/volkaportal/spaceship-api-key")
    )
    parser.add_argument(
        "--secret-file", type=Path, default=Path("/etc/volkaportal/spaceship-api-secret")
    )
    args = parser.parse_args()
    key = args.key_file.read_text(encoding="utf-8").strip()
    secret = args.secret_file.read_text(encoding="utf-8").strip()
    if not key or not secret:
        parser.error("Spaceship DNS credentials are empty")

    wildcard = [item for item in records(key, secret) if item.get("name") == "*"]
    if wildcard:
        if len(wildcard) == 1 and wildcard[0].get("type") == "A" and wildcard[0].get("address") == TARGET_IP:
            print(f"Wildcard DNS already points to {TARGET_IP}")
            return
        raise RuntimeError("Existing wildcard DNS record differs; no changes made")

    if not args.apply:
        print(f"Would add *. {DOMAIN} A {TARGET_IP}; pass --apply to proceed")
        return

    request(
        "PUT",
        key,
        secret,
        payload={"force": False, "items": [{"type": "A", "name": "*", "address": TARGET_IP, "ttl": 1800}]},
    )
    if not any(item.get("name") == "*" and item.get("type") == "A" and item.get("address") == TARGET_IP for item in records(key, secret)):
        raise RuntimeError("Wildcard DNS write could not be verified")
    print(f"Wildcard DNS now points to {TARGET_IP}")


if __name__ == "__main__":
    main()
