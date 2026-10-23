"""facts.md as Diana's memory: ids on lines, corrections replace (old wording logged), pin, edit, forget, hand edits kept.
Run: python3 -m unittest discover tests"""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))


class Facts(unittest.TestCase):
    def setUp(self):
        self.home, self.vault = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.environ.update({"STEWARD_HOME": self.home, "STEWARD_VAULT": self.vault, "STEWARD_KEY": "k"})
        import steward_server
        self.S = importlib.reload(steward_server)
        from fastapi.testclient import TestClient
        self.c, self.h = TestClient(self.S.app), {"Authorization": "Bearer k"}
        self.f = Path(self.vault) / "Diana" / "facts.md"
        self.addCleanup(os.environ.pop, "STEWARD_VAULT", None)

    def facts(self):
        return self.c.get("/v1/vault/facts", headers=self.h).json()["facts"]

    def test_hand_written_lines_and_other_text_survive(self):
        self.f.write_text("# Facts\n\nMy own note, not a fact.\n\n- You coach guitar on Tuesdays.\n")
        [f] = self.facts()
        self.assertEqual(f["text"], "You coach guitar on Tuesdays.")
        self.c.post("/v1/vault/facts", headers=self.h, json={"id": "m1", "text": "You prefer morning meetings."})
        self.c.patch("/v1/vault/facts/" + f["id"], headers=self.h, json={"pinned": True})
        text = self.f.read_text()
        self.assertIn("My own note, not a fact.", text)
        self.assertIn("- You coach guitar on Tuesdays. #pinned", text)
        self.assertTrue(any(x["pinned"] for x in self.facts()))

    def test_correction_replaces_and_logs_old_wording(self):
        self.c.post("/v1/vault/facts", headers=self.h, json={"id": "m1", "text": "You prefer morning meetings.", "pinned": True})
        r = self.c.post("/v1/vault/facts", headers=self.h, json={"id": "m2", "text": "You do not prefer morning meetings.", "replaces": "m1"}).json()
        self.assertEqual(r["replaced"], "m1")
        [f] = self.facts()
        self.assertEqual((f["id"], f["text"], f["pinned"]), ("m2", "You do not prefer morning meetings.", True))
        log = next((Path(self.vault) / "Diana" / "memory").glob("*.md")).read_text()
        self.assertIn("Was: You prefer morning meetings.", log)

    def test_exact_repeat_not_added(self):
        for _ in range(2):
            self.c.post("/v1/vault/facts", headers=self.h, json={"text": "You prefer morning meetings."})
        self.assertEqual(len(self.facts()), 1)

    def test_edit_and_forget(self):
        self.c.post("/v1/vault/facts", headers=self.h, json={"id": "m1", "text": "Your supervisor is Peggy."})
        self.c.patch("/v1/vault/facts/m1", headers=self.h, json={"text": "Your supervisor is Peggy McGee."})
        self.assertEqual(self.facts()[0]["text"], "Your supervisor is Peggy McGee.")
        self.c.delete("/v1/vault/facts/m1", headers=self.h)
        self.assertEqual(self.facts(), [])
        self.assertNotIn("Peggy", self.f.read_text())

    def test_remember_bulk_gets_ids(self):
        self.c.post("/v1/vault/remember", headers=self.h, json={"facts": ["You like coffee.", "You teach guitar."]})
        self.assertTrue(all(x["id"] for x in self.facts()))
        self.assertEqual(self.f.read_text().count(" ^"), 2)

    def test_profile_without_vault(self):
        os.environ.pop("STEWARD_VAULT")
        S = importlib.reload(self.S)
        (Path(self.home) / "docs" / "about-me.md").write_text("JP works in THQ Youth.")
        self.assertEqual(S._profile_text(), "JP works in THQ Youth.")
