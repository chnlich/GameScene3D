"""HTTP and local asset tests use offline files, never model inference."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from server.app import create_app
from server.config import load_config
from server.files import ROOT, public_safe, validate
from server.runtime import capability
from conftest import image_bytes, submit_text


def test_honest_missing_pipeline(config, tmp_path, monkeypatch):
    monkeypatch.setattr("server.runtime.shutil.which", lambda name: f"/test/{name}")

    def missing(name):
        raise ModuleNotFoundError("pipeline.runner missing")

    monkeypatch.setattr("server.runtime.importlib.import_module", missing)
    with TestClient(create_app(config, root=tmp_path)) as client:
        health = client.get("/api/health").json()
        validate("Health", health)
        assert health["ok"] and not health["generation_available"]
        assert "pipeline.runner" in health["generation_note"]
        response = submit_text(client)
        assert response.status_code == 503
        validate("Error", response.json())
        assert client.get("/").status_code == 503
        assert client.get("/api/examples").json() == []


@pytest.mark.parametrize("missing", ["config", "codex", "blender"])
def test_missing_prerequisite(config, monkeypatch, missing):
    if missing == "config":
        config.generation_config.unlink()
    monkeypatch.setattr("server.runtime.shutil.which", lambda name: None if name == missing else f"/test/{name}")
    generate, note = capability(config)
    assert generate is None
    assert ("configuration" if missing == "config" else missing) in note
    assert str(config.generation_config) not in note


def test_materials_catalog_provenance(config, tmp_path):
    materials = tmp_path / "demo/materials"
    (materials / "images").mkdir(parents=True)
    (materials / "images/input.png").write_bytes(image_bytes())
    entry = {
        "file": "images/input.png", "title": "Provided input", "category": "Category",
        "visible_checks": "Pose", "generated_scene": None, "source": "https://source.example/image",
        "license": "Provided license", "license_url": None, "attribution": "Original author",
        "changes": "Original bytes; candidate input only",
    }
    catalog = materials / "catalog.json"
    catalog.write_text(json.dumps([entry]))
    with TestClient(create_app(config, root=tmp_path)) as client:
        example = client.get("/api/examples").json()[0]
        validate("Example", example)
        assert example["kind"] == "input"
        for key in ("title", "source", "license", "license_url", "attribution", "changes"):
            assert example[key] == entry[key]
        assert client.get(example["input"]["image_url"]).content == image_bytes()
        entry["attribution"] = "Updated author"
        catalog.write_text(json.dumps([entry]))
        assert client.get("/api/examples").json()[0]["attribution"] == "Updated author"


def test_vendor_and_ui_routes(config, tmp_path):
    vendor = tmp_path / "node_modules/three"
    vendor.mkdir(parents=True)
    (vendor / "module.js").write_text("export const offlineFixture = true;")
    (vendor / "decoder.wasm").write_bytes(b"\0asm\x01\0\0\0")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<p>Offline viewer routing fixture</p>")
    (web / "app.js").write_text("export {};")
    (tmp_path / "private.txt").write_text("private")
    (web / "escape.txt").symlink_to(tmp_path / "private.txt")
    (vendor / "escape.txt").symlink_to(tmp_path / "private.txt")
    with TestClient(create_app(config, root=tmp_path)) as client:
        assert "Offline viewer" in client.get("/").text
        assert client.get("/app.js").headers["content-type"].startswith("text/javascript")
        assert client.get("/vendor/three/module.js").headers["content-type"].startswith("text/javascript")
        assert client.get("/vendor/three/decoder.wasm").headers["content-type"] == "application/wasm"
        assert client.get("/api/health").json()["ok"]
        for path in ("/escape.txt", "/vendor/three/escape.txt", "/vendor/other/module.js", "/vendor/three/%2e%2e/private.txt", "/api/missing", "/private.txt", "/%2e%2e/private.txt"):
            response = client.get(path)
            assert response.status_code == 404, path
            validate("Error", response.json())


def test_installed_three_version_and_assets(config):
    package = json.loads((ROOT / "package.json").read_text())
    installed = json.loads((ROOT / "node_modules/three/package.json").read_text())
    assert package["dependencies"]["three"] == installed["version"] == "0.185.1"
    with TestClient(create_app(config)) as client:
        for file, mime in (
            ("build/three.module.js", "text/javascript"),
            ("examples/jsm/libs/draco/gltf/draco_decoder.wasm", "application/wasm"),
        ):
            response = client.get("/vendor/three/" + file)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(mime)


def test_pixel_limit_and_duplicate_field(offline_client):
    stream = io.BytesIO()
    Image.new("RGB", (50, 50)).save(stream, format="PNG")
    response = offline_client.post("/api/jobs", files={"image": ("big.png", stream.getvalue())})
    assert response.status_code == 422
    response = offline_client.post("/api/jobs", files=[("prompt", (None, "one")), ("prompt", (None, "two"))])
    assert response.status_code == 422


def test_root_config_validation(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text((ROOT / "config.example.yaml").read_text())
    config = load_config(path)
    assert config.host == "127.0.0.1"
    assert config.data_dir == tmp_path / "runtime/jobs"
    path.write_text(path.read_text() + "unknown: true\n")
    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize("value", ["/home/user/private", "C:\\Users\\private", {"api_key": "sensitive"}, "Bearer sensitive"])
def test_private_output_rejected(value):
    with pytest.raises(ValueError):
        public_safe(value)


def test_symlink_asset_mounts_are_rejected(config, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.js").write_text("private")
    (tmp_path / "demo").symlink_to(outside, target_is_directory=True)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules/three").symlink_to(outside, target_is_directory=True)
    with TestClient(create_app(config, root=tmp_path)) as client:
        assert client.get("/demo/secret.js").status_code == 404
        assert client.get("/vendor/three/secret.js").status_code == 404
