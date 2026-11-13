"""The HTTP API behind the web interface, driven end to end with the fake agents of test_graph."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from sysrev import api
from test_graph import calls  # noqa: F401  (fixture: fake agents, temporary runs folder)


def wait_for(client: TestClient, run_id: str, states: tuple[str, ...], timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"]["state"] in states:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run still {run['status']['state']}: {run['status']}")


def test_review_through_the_three_checkpoints(calls):  # noqa: F811
    api._jobs.clear(), api._runners.clear()
    client = TestClient(api.app)
    assert client.get("/api/runs").json() == []

    run_id = client.post("/api/runs", json={"question": "Does the fake intervention work?"}).json()["id"]

    run = wait_for(client, run_id, ("waiting", "error"))
    assert run["pending"]["checkpoint"] == "protocol" and run["protocol"]["title"]
    assert [s["state"] for s in run["status"]["steps"]][:3] == ["done", "done", "now"]

    # the reviewer asks for changes: the planner runs again and the checkpoint comes back
    assert client.post(f"/api/runs/{run_id}/advance", json={"resume": {"action": "revise", "feedback": "adults only"}}).status_code == 200
    run = wait_for(client, run_id, ("waiting", "error"))
    assert run["pending"]["checkpoint"] == "protocol" and calls["protocol"] == 2

    client.post(f"/api/runs/{run_id}/advance", json={"resume": {"action": "approve"}})
    run = wait_for(client, run_id, ("waiting", "error"))
    assert run["pending"]["checkpoint"] == "screening"
    excluded = next(d["rid"] for d in run["pending"]["decisions"] if d["final"] == "exclude")

    client.post(f"/api/runs/{run_id}/advance", json={"resume": {"action": "approve", "overrides": {excluded: "include"}}})
    run = wait_for(client, run_id, ("waiting", "error"))
    assert run["pending"]["checkpoint"] == "report"
    assert next(d for d in run["screening"]["title_abstract"] if d["rid"] == excluded)["final"] == "include"

    client.post(f"/api/runs/{run_id}/advance", json={"resume": {"action": "approve"}})
    run = wait_for(client, run_id, ("finished", "error"))
    assert run["status"]["state"] == "finished" and run["pending"] is None
    assert all(s["state"] == "done" for s in run["status"]["steps"])
    assert run["report"]["final"] and "report.md" in run["files"]

    assert client.get("/api/runs").json()[0]["state"] == "finished"
    assert "# " in client.get(f"/api/runs/{run_id}/report").json()["markdown"]
    assert client.get(f"/api/runs/{run_id}/audit").json()[0]["action"] == "run created"
    assert client.get(f"/api/runs/{run_id}/files/report.md").status_code == 200

    # a finished review accepts no further decision
    assert client.post(f"/api/runs/{run_id}/advance", json={"resume": {"action": "approve"}}).status_code == 409
    assert client.post(f"/api/runs/{run_id}/advance", json={}).status_code == 409


def test_api_refuses_unknown_runs_files_and_bad_input(calls):  # noqa: F811
    api._jobs.clear(), api._runners.clear()
    client = TestClient(api.app)
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/..%2F..%2F.env").status_code == 404
    assert client.post("/api/runs", json={"question": "short"}).status_code == 422
    assert client.post("/api/runs", json={"question": "A long enough question?", "fulltext_fallback": "delete"}).status_code == 422

    run_id = client.post("/api/runs", json={"question": "Does the fake intervention work?", "auto": True}).json()["id"]
    run = wait_for(client, run_id, ("finished", "error"))
    assert run["status"]["state"] == "finished"
    assert client.get(f"/api/runs/{run_id}/files/manifest.json").status_code == 404  # not in the download list
    assert client.get(f"/api/runs/{run_id}/files/checkpoints.sqlite").status_code == 404
