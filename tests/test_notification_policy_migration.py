"""Standalone migration regression tests; no app factory, seed or live DB.

Run: venv/Scripts/python.exe -B tests/test_notification_policy_migration.py
"""

import ast
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "notification_migration_verifier", ROOT / "scripts/verify_notification_policy_migration.py"
)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class NotificationPolicyMigrationTests(unittest.TestCase):
    def test_minimal_predecessor_roundtrip(self):
        directory = Path(tempfile.mkdtemp(prefix=".tmp-notification-policy-test-", dir=ROOT))
        path = directory / "migration.db"
        with sqlite3.connect(path) as connection:
            connection.executescript("""
                CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY NOT NULL);
                INSERT INTO alembic_version VALUES ('202610020001');
                CREATE TABLE companies (id INTEGER PRIMARY KEY);
                INSERT INTO companies VALUES (1), (2);
                CREATE TABLE users (id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id));
                INSERT INTO users VALUES (1, 1), (2, 2);
                CREATE TABLE notifications (id INTEGER PRIMARY KEY, company_id INTEGER REFERENCES companies(id), user_id INTEGER REFERENCES users(id), message TEXT);
                INSERT INTO notifications VALUES (1, 1, 1, 'Existing notification');
                CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO app_settings VALUES ('existing-setting', 'preserve-me');
            """)
        evidence = {}
        try:
            verifier.rehearse(path, evidence)
            self.assertEqual(evidence["result"], "PASS_WITH_OBSERVATIONS")
            self.assertEqual(len(evidence["stages"]), 8)
            self.assertEqual(len(evidence["metadata"]), 4)
            self.assertTrue(evidence["reviewed_sources_stable_during_rehearsal"])
            self.assertFalse(evidence["factory_or_seed_executed"])
        except BaseException as error:
            evidence.update(result="FAILED", failure=repr(error))
            raise
        finally:
            output = directory / "evidence.json"
            output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print(f"EVIDENCE={output}", flush=True)

    def test_migration_does_not_import_mutable_application_models(self):
        tree = ast.parse(verifier.MIGRATION.read_text(encoding="utf-8-sig"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "app":
                imports.append((node.lineno, node.module))
            elif isinstance(node, ast.Import):
                imports.extend((node.lineno, alias.name) for alias in node.names if alias.name.split(".")[0] == "app")
        self.assertEqual(imports, [], "Freeze table definitions inside the revision; app model imports make historical migrations change with future code")


if __name__ == "__main__":
    unittest.main(verbosity=2)
