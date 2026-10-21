"""Diana's notes in an Obsidian vault: setup, append-only log, deduplicated facts, writes stay in her folder.
Run: python3 -m unittest discover tests"""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))


class Vault(unittest.TestCase):
    def setUp(self):
        self.home, self.vault = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.environ.update({"STEWARD_HOME": self.home, "STEWARD_VAULT": self.vault, "STEWARD_KEY": "k"})
        import steward_server
        self.S = importlib.reload(steward_server)
        from fastapi.testclient import TestClient
        self.c, self.h = TestClient(self.S.app), {"Authorization": "Bearer k"}
        self.d = Path(self.vault) / "Diana"

    def tearDown(self):
        os.environ.pop("STEWARD_VAULT", None)

    def test_setup_and_feature(self):
        for f in ("DIANA.md", "facts.md", "guides/diana-notes.md"):
            self.assertTrue((self.d / f).exists(), f)
        self.assertIn("vault", self.c.get("/health").json()["features"])

    def test_log_appends(self):
        for line in ("first", "second"):
            self.c.post("/v1/vault/log", headers=self.h, json={"lines": [line]})
        log = next((self.d / "memory").glob("*.md")).read_text()
        self.assertIn("first", log); self.assertIn("second", log)

    def test_facts_deduplicated(self):
        r = self.c.post("/v1/vault/remember", headers=self.h, json={"facts": ["Likes mornings.", "Likes mornings."]}).json()
        self.assertEqual(r["added"], 1)
        self.assertEqual(self.c.post("/v1/vault/remember", headers=self.h, json={"facts": ["Likes mornings."]}).json()["added"], 0)

    def test_person_page_stays_in_folder(self):
        self.c.post("/v1/vault/remember", headers=self.h, json={"facts": ["Supervisor."], "person": "../../Peggy"})
        pages = list((self.d / "people").glob("*.md"))
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].resolve().is_relative_to(self.d.resolve()))

    def test_needs_key(self):
        self.assertEqual(self.c.post("/v1/vault/log", json={"lines": ["x"]}).status_code, 401)
