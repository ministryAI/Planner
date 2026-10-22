"""Read-only public API (for outside agents like Muse): auth, response shapes, pagination, read-only, no redirects.
Run: python3 -m unittest discover tests"""
import importlib
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

H = 3600000
NOW = int(time.time() * 1000)


class PublicApi(unittest.TestCase):
    def setUp(self):
        os.environ.update({"STEWARD_HOME": tempfile.mkdtemp(), "STEWARD_KEY": "main-key", "STEWARD_TIMEZONE": "America/Chicago"})
        os.environ.pop("STEWARD_VAULT", None)
        import steward_server
        self.S = importlib.reload(steward_server)
        from fastapi.testclient import TestClient
        self.main, self.api = TestClient(self.S.app), TestClient(self.S.api, follow_redirects=False)
        self.S.STORE.update(loaded=True, data={"planner": {
            "projects": [{"id": "p1", "name": "BLESS Curriculum"}],
            "tasks": [{"id": "t1", "title": "Prepare youth talk", "status": "todo", "priority": "high", "deadline": NOW + 24 * H, "projectId": "p1", "labels": ["youth"], "created": NOW - H},
                      {"id": "t2", "title": "Old thing", "status": "done", "priority": "med", "created": NOW - 48 * H, "completed": NOW - H},
                      {"id": "t3", "title": "Sample", "status": "todo", "sample": True}] + [{"id": f"x{i}", "title": f"Bulk {i}", "status": "todo", "created": NOW} for i in range(5)],
            "events": [{"id": "e1", "title": "Team meeting", "start": NOW + H, "end": NOW + 2 * H, "created": NOW - H},
                       {"id": "e2", "title": "Imported", "start": NOW + H, "end": NOW + 2 * H, "src": "ics"}]}})
        self.key = self.main.post("/v1/apikeys", headers={"Authorization": "Bearer main-key"}, json={"label": "Muse"}).json()["key"]
        self.h = {"Authorization": "Bearer " + self.key}

    def test_auth(self):
        self.assertEqual(self.api.get("/v1/me").status_code, 401)
        r = self.api.get("/v1/me", headers={"Authorization": "Bearer main-key"})  # the Steward key doesn't open this API
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "unauthorized"))
        self.assertEqual(self.api.get("/v1/me", headers=self.h).json()["user"]["timezone"], "America/Chicago")

    def test_tasks_shape_and_filters(self):
        tasks = self.api.get("/v1/tasks?limit=50", headers=self.h).json()
        self.assertEqual(len(tasks["tasks"]), 6)  # open, samples left out
        t = tasks["tasks"][0]
        self.assertEqual((t["id"], t["list"], t["priority"], t["tags"], t["notes"]), ("task_t1", "BLESS Curriculum", "high", ["youth"], None))
        self.assertTrue(t["due_at"].endswith(("-05:00", "-06:00")))
        done = self.api.get("/v1/tasks?status=completed", headers=self.h).json()["tasks"]
        self.assertEqual([x["id"] for x in done], ["task_t2"])
        self.assertIsNotNone(done[0]["completed_at"])
        due = self.api.get("/v1/tasks", params={"due_from": t["due_at"], "due_to": t["due_at"]}, headers=self.h).json()["tasks"]
        self.assertEqual([x["id"] for x in due], ["task_t1"])
        self.assertEqual(self.api.get("/v1/tasks/task_t1", headers=self.h).json()["task"]["title"], "Prepare youth talk")
        self.assertEqual(self.api.get("/v1/tasks/task_nope", headers=self.h).status_code, 404)

    def test_pagination(self):
        seen, cur = [], None
        for _ in range(10):
            j = self.api.get("/v1/tasks", params={"limit": 4, **({"cursor": cur} if cur else {})}, headers=self.h).json()
            seen += [t["id"] for t in j["tasks"]]; cur = j["next_cursor"]
            if not cur:
                break
        self.assertEqual(len(seen), 6); self.assertEqual(len(set(seen)), 6)

    def test_schedule(self):
        self.assertEqual(self.api.get("/v1/schedule", headers=self.h).status_code, 400)
        start = self.S._iso(NOW); end = self.S._iso(NOW + 24 * H)
        evs = self.api.get("/v1/schedule", params={"from": start, "to": end}, headers=self.h).json()["events"]
        self.assertEqual([e["id"] for e in evs], ["evt_e1"])  # calendar imports and the work feed stay out by default
        self.assertEqual(evs[0]["status"], "confirmed")

    def test_read_only_and_no_redirects(self):
        self.assertEqual(self.api.post("/v1/tasks", headers=self.h).status_code, 405)
        r = self.api.get("/v1/tasks/", headers=self.h)
        self.assertNotIn(r.status_code, (301, 302, 307, 308))
        self.assertEqual(r.headers["content-type"], "application/json")
        self.assertEqual(self.api.get("/v1/sync", headers=self.h).status_code, 404)  # nothing else is exposed

    def test_revoke(self):
        kid = self.main.get("/v1/apikeys", headers={"Authorization": "Bearer main-key"}).json()["keys"][0]["id"]
        self.main.delete("/v1/apikeys/" + kid, headers={"Authorization": "Bearer main-key"})
        self.assertEqual(self.api.get("/v1/me", headers=self.h).status_code, 401)

    def test_key_not_stored(self):
        self.assertNotIn(self.key, self.S.API_KEYS_FILE.read_text())
