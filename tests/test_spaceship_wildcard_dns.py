import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "tls" / "spaceship_wildcard_dns.py"
SPEC = importlib.util.spec_from_file_location("spaceship_wildcard_dns", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def run_main(monkeypatch, tmp_path, *, apply=False):
    key = tmp_path / "key"
    secret = tmp_path / "secret"
    key.write_text("test-key", encoding="utf-8")
    secret.write_text("test-secret", encoding="utf-8")
    argv = ["spaceship_wildcard_dns.py", "--key-file", str(key), "--secret-file", str(secret)]
    if apply:
        argv.append("--apply")
    monkeypatch.setattr(sys, "argv", argv)
    MODULE.main()


def test_existing_matching_record_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        MODULE,
        "records",
        lambda *_: [{"name": "*", "type": "A", "address": MODULE.TARGET_IP}],
    )
    monkeypatch.setattr(MODULE, "request", lambda *_args, **_kwargs: pytest.fail("unexpected write"))
    run_main(monkeypatch, tmp_path, apply=True)


def test_conflicting_record_is_not_overwritten(monkeypatch, tmp_path):
    monkeypatch.setattr(
        MODULE,
        "records",
        lambda *_: [{"name": "*", "type": "A", "address": "192.0.2.1"}],
    )
    monkeypatch.setattr(MODULE, "request", lambda *_args, **_kwargs: pytest.fail("unexpected write"))
    with pytest.raises(RuntimeError, match="differs"):
        run_main(monkeypatch, tmp_path, apply=True)


def test_apply_verifies_new_record(monkeypatch, tmp_path):
    calls = []

    def record_list(*_args):
        return [] if not calls else [{"name": "*", "type": "A", "address": MODULE.TARGET_IP}]

    def save(method, *_args, **kwargs):
        calls.append((method, kwargs["payload"]))

    monkeypatch.setattr(MODULE, "records", record_list)
    monkeypatch.setattr(MODULE, "request", save)
    run_main(monkeypatch, tmp_path, apply=True)
    assert calls == [
        (
            "PUT",
            {
                "force": False,
                "items": [{"type": "A", "name": "*", "address": MODULE.TARGET_IP, "ttl": 1800}],
            },
        )
    ]
