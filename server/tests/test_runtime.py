"""Offline plumbing tests; no provider, Codex, Blender, or paid generation calls."""
import json
import threading

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.files import atomic_json, contained_file, validate
from server.runtime import Runtime
from conftest import finished, image_bytes, offline_generate, submit_text


@pytest.mark.parametrize("with_image", [True, False])
def test_submission_and_public_artifacts(offline_client, config, with_image):
    files = {"prompt": (None, "current input $(no shell) `no command`")}
    if with_image:
        files["image"] = ("../../malicious.png", image_bytes(), "application/octet-stream")
    response = offline_client.post("/api/jobs", files=files)
    assert response.status_code == 202
    validate("Job", response.json())
    job = finished(offline_client, response.json()["id"])
    assert job["status"] == "succeeded", job
    validate("Job", job)
    result = job["result"]
    assert result["elapsed_seconds"] > 0
    for url in result["artifacts"].values():
        if url:
            assert url.startswith(f"/artifacts/{job['id']}/")
            assert offline_client.get(url).status_code == 200
    directory = config.data_dir / job["id"]
    if with_image:
        assert (directory / "original.png").read_bytes() == image_bytes()
    else:
        assert result["artifacts"]["original"] is None
    assert str(config.generation_config) not in json.dumps(job)
    assert str(config.generation_config) not in (directory / "request.json").read_text()
    assert offline_client.get(f"/artifacts/{job['id']}/request.json").status_code == 404


@pytest.mark.parametrize("files", [
    {"prompt": (None, "  ")},
    {"image": ("x.png", b"not image", "image/png")},
    {"image": ("x.png", b"", "image/png")},
    {"image": ("x.png", b"x" * 2050, "image/png")},
    {"prompt": (None, "x" * 101)},
    {"extra": (None, "unknown")},
    {"image": (None, "not a file")},
    {"prompt": ("x.txt", b"not a field")},
])
def test_invalid_inputs(offline_client, files):
    response = offline_client.post("/api/jobs", files=files)
    assert response.status_code == 422
    validate("Error", response.json())


def test_empty_malformed_and_body_limit(offline_client):
    for body, content_type in [
        (b"", "application/json"),
        (b"broken", "multipart/form-data"),
        (b"x" * 5000, "multipart/form-data; boundary=test"),
        (b"--test\r\nInvalid header\r\n", "multipart/form-data; boundary=test"),
    ]:
        response = offline_client.post("/api/jobs", content=body, headers={"Content-Type": content_type})
        assert response.status_code == 422, response.text
        validate("Error", response.json())


@pytest.mark.parametrize("fault", ["progress", "swallowed_progress", "result", "glb", "evidence", "private", "path", "symlink", "original", "exception"])
def test_failure_preserves_evidence(config, tmp_path, monkeypatch, fault):
    def broken(request, directory, progress):
        result = offline_generate(request, directory, progress)
        if fault in ("progress", "swallowed_progress"):
            try:
                progress({"phase": "bad", "message": "bad", "fraction": 2})
            except Exception:
                if fault == "progress":
                    raise
                # Deliberately misbehaving fixture proves swallowed validation cannot succeed.
                (directory / "ignored-callback.txt").write_text("Test pipeline swallowed callback failure")
        elif fault == "result":
            result["undocumented"] = True
        elif fault == "glb":
            (directory / "scene.glb").write_bytes(b"fake")
        elif fault == "evidence":
            (directory / "evidence.json").write_text("{}")
        elif fault == "private":
            result["summary"] = "/home/private/secret api_key=confidential"
        elif fault == "path":
            result["artifacts"]["glb"] = "../outside.glb"
        elif fault == "symlink":
            (directory / "scene.glb").rename(directory / "other.glb")
            (directory / "scene.glb").symlink_to(directory / "other.glb")
        elif fault == "original":
            result["artifacts"]["original"] = "preview.png"
        elif fault == "exception":
            raise RuntimeError("/home/private/config.yaml api_key=confidential")
        return result

    monkeypatch.setattr("server.runtime.capability", lambda config: (broken, "Offline fixture"))
    with TestClient(create_app(config, root=tmp_path)) as client:
        job = finished(client, submit_text(client).json()["id"])
        assert job["status"] == "failed", job
        validate("Error", job["error"])
        assert "confidential" not in json.dumps(job)
        assert "/home/private" not in json.dumps(job)
        assert (config.data_dir / job["id"] / "evidence.json").exists()
        assert job["result"] is None


def test_queue_and_event_loop_liveness(config, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked(request, directory, progress):
        calls.append(request)
        entered.set()
        assert release.wait(3)
        return offline_generate(request, directory, progress)

    monkeypatch.setattr("server.runtime.capability", lambda config: (blocked, "Offline fixture"))
    with TestClient(create_app(config, root=tmp_path)) as client:
        try:
            first = submit_text(client).json()
            assert entered.wait(1)
            second = submit_text(client).json()
            assert client.get(f"/api/jobs/{first['id']}").json()["status"] == "running"
            assert client.get(f"/api/jobs/{second['id']}").json()["status"] == "queued"
            assert len(calls) == 1
            assert submit_text(client).status_code == 503
            assert client.get("/api/health").status_code == 200
            assert calls[0]["config_path"] == str(config.generation_config)
        finally:
            release.set()
        assert finished(client, first["id"])["status"] == "succeeded"
        assert finished(client, second["id"])["status"] == "succeeded"


def test_stale_jobs_and_exclusive_ownership(config, tmp_path):
    config.data_dir.mkdir()
    for status in ("queued", "running"):
        job_id = ("a" if status == "queued" else "b") * 32
        directory = config.data_dir / job_id
        directory.mkdir()
        (directory / "partial.txt").write_text("Preserved partial evidence")
        atomic_json(directory / "job.json", {
            "id": job_id, "status": status,
            "progress": {"phase": "old", "message": "Old process", "fraction": None},
            "input": {"prompt": "test", "image_url": None}, "result": None, "error": None,
        })
    with TestClient(create_app(config, root=tmp_path)) as client:
        another = Runtime(config)
        with pytest.raises(RuntimeError, match="live server"):
            another.start()
        for character in ("a", "b"):
            job_id = character * 32
            job = client.get(f"/api/jobs/{job_id}").json()
            assert job["status"] == "failed"
            assert job["error"]["code"] == "interrupted"
            assert (config.data_dir / job_id / "partial.txt").exists()


@pytest.mark.parametrize("reference", ["../secret", "/etc/passwd", "a/../../secret", "%2e%2e/secret", "a\\secret", "https://host/file", "file?x=1"])
def test_path_containment(tmp_path, reference):
    with pytest.raises(ValueError):
        contained_file(tmp_path, reference)


def test_success_depends_on_remaining_files(offline_client, config):
    job = finished(offline_client, submit_text(offline_client).json()["id"])
    assert job["status"] == "succeeded"
    (config.data_dir / job["id"] / "scene.glb").unlink()
    missing = offline_client.get(f"/api/jobs/{job['id']}").json()
    assert missing["status"] == "failed"
    assert missing["error"]["code"] == "artifacts_unavailable"
    assert (config.data_dir / job["id"] / "evidence.json").exists()


def test_truncated_multipart_cannot_become_text_only(offline_client):
    body = (
        b'--test\r\nContent-Disposition: form-data; name="prompt"\r\n\r\nusable prompt\r\n'
        b'--test\r\nContent-Disposition: form-data; name="image"; filename="image.png"\r\n\r\ntruncated'
    )
    response = offline_client.post("/api/jobs", content=body, headers={"Content-Type": "multipart/form-data; boundary=test"})
    assert response.status_code == 422
    validate("Error", response.json())
