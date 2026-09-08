"""Offline plumbing fixtures. The triangle is a test artifact, never user generation."""
import io
import json
import struct
import time
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Config
from server.files import atomic_json


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (12, 8), "blue").save(stream, format="PNG")
    return stream.getvalue()


def offline_generate(request, output_dir, on_progress):
    on_progress({"phase": "offline-test", "message": "Plumbing fixture only; no inference.", "fraction": 0.5})
    binary = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    scene = {
        "asset": {"version": "2.0", "generator": "offline plumbing test"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}],
    }
    encoded = json.dumps(scene).encode()
    encoded += b" " * (-len(encoded) % 4)
    data = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(encoded) + 8 + len(binary))
    data += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    data += struct.pack("<II", len(binary), 0x004E4942) + binary
    (output_dir / "scene.glb").write_bytes(data)
    (output_dir / "preview.png").write_bytes(image_bytes())
    atomic_json(output_dir / "evidence.json", {"provider": "offline plumbing fake", "calls": [], "cost_usd": None})
    return {
        "title": "Offline fixture", "summary": "Plumbing only; no user generation.",
        "artifacts": {"glb": "scene.glb", "original": Path(request["image_path"]).name if request["image_path"] else None,
                      "preview": "preview.png", "evidence": "evidence.json", "blend": None, "manifest": None},
        "camera": None, "assumptions": ["Offline test"], "elapsed_seconds": None,
        "cost_usd": None, "cost_note": "No inference; cost not applicable.",
    }


@pytest.fixture
def config(tmp_path):
    generation = tmp_path / "generation.yaml"
    generation.write_text("provider: test-only\n")
    return Config(
        host="127.0.0.1", port=18765, data_dir=tmp_path / "jobs", generation_config=generation,
        max_concurrency=1, max_queued=1, max_upload_bytes=2048, max_request_bytes=4096,
        max_prompt_chars=100, max_image_pixels=1000,
    )


@pytest.fixture
def offline_client(config, tmp_path, monkeypatch):
    monkeypatch.setattr("server.runtime.capability", lambda config: (offline_generate, "Offline plumbing fixture"))
    with TestClient(create_app(config, root=tmp_path)) as client:
        yield client


def submit_text(client, prompt="A triangle"):
    return client.post("/api/jobs", files={"prompt": (None, prompt)})


def finished(client, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.01)
    raise AssertionError("Offline job did not complete")
