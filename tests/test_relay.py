"""GitHub relay: writes me/tasks/schedule JSON to a private repo, commits only what changed. Uses a fake GitHub.
Run: python3 -m unittest discover tests"""
import asyncio
import base64
import importlib
import json
import os
import sys
import tempfile
import time
import unittest

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
NOW = int(time.time() * 1000)


class Relay(unittest.TestCase):
    def setUp(self):
        os.environ.update({"STEWARD_HOME": tempfile.mkdtemp(), "STEWARD_KEY": "k", "STEWARD_GITHUB_TOKEN": "ghp_test", "STEWARD_GITHUB_REPO": "me/steward-data"})
        os.environ.pop("STEWARD_VAULT", None)
        import steward_server
        self.S = importlib.reload(steward_server)
        self.S.STORE.update(loaded=True, data={"planner": {"tasks": [{"id": "t1", "title": "Prepare youth talk", "status": "todo", "deadline": NOW + 3600000, "created": NOW}],
                                                           "events": [{"id": "e1", "title": "Team meeting", "start": NOW + 3600000, "end": NOW + 7200000}]}})
        self.files, self.puts = {}, []

        def handler(req):
            assert req.headers["authorization"] == "Bearer ghp_test"
            path = req.url.path.split("/contents/", 1)[1]
            if req.method == "GET":
                f = self.files.get(path)
                return httpx.Response(200, json={"sha": f["sha"], "content": f["content"]}) if f else httpx.Response(404, json={})
            body = json.loads(req.content)
            if path in self.files and body.get("sha") != self.files[path]["sha"]:
                return httpx.Response(409, json={"message": "sha mismatch"})
            sha = "s%d" % (len(self.puts) + 1)
            self.files[path] = {"sha": sha, "content": body["content"]}
            self.puts.append(path)
            return httpx.Response(201, json={"content": {"sha": sha}})

        real = httpx.AsyncClient
        self.S.httpx.AsyncClient = lambda **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"})
        self.addCleanup(setattr, self.S.httpx, "AsyncClient", real)
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("STEWARD_GITHUB_TOKEN", "STEWARD_GITHUB_REPO")])

    def read(self, name):
        return json.loads(base64.b64decode(self.files["steward/" + name]["content"]))

    def test_writes_and_skips_unchanged(self):
        asyncio.run(self.S._relay_push())
        self.assertIsNone(self.S.RELAY["error"])
        self.assertEqual(sorted(self.puts), ["steward/me.json", "steward/schedule.json", "steward/tasks.json"])
        self.assertEqual(self.read("tasks.json")["tasks"][0]["id"], "task_t1")
        self.assertEqual(self.read("schedule.json")["events"][0]["id"], "evt_e1")
        self.assertIn("as_of", self.read("me.json"))
        asyncio.run(self.S._relay_push())
        self.assertEqual(len(self.puts), 3)  # nothing changed, nothing committed
        self.S.STORE["data"]["planner"]["tasks"][0]["title"] = "Prepare youth talk v2"
        asyncio.run(self.S._relay_push())
        self.assertEqual(self.puts[3:], ["steward/tasks.json"])

    def test_restart_does_not_recommit(self):
        asyncio.run(self.S._relay_push())
        self.S.RELAY.update(shas={}, hashes={})  # a fresh server process
        asyncio.run(self.S._relay_push())
        self.assertEqual(len(self.puts), 3)
