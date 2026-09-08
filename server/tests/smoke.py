"""Start the real CLI on an unused loopback port, read assets, and stop it. No inference."""
import json
import shutil
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import yaml

from server.files import ROOT, SCHEMA, validate


def main():
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("Run this recipe from the repository root")
    if shutil.which("uv") is None:
        raise RuntimeError("Install uv before running the startup recipe")
    package = json.loads((ROOT / "node_modules/three/package.json").read_text())
    expected = json.loads((ROOT / "package.json").read_text())["dependencies"]["three"]
    if package["version"] != expected or expected not in SCHEMA["x-web"]["dependency"]:
        raise RuntimeError("Run npm ci to install the contract-pinned three package")
    directory = ROOT / "runtime" / ("startup-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = yaml.safe_load((ROOT / "config.example.yaml").read_text())
    config.update(host="127.0.0.1", port=port, data_dir="jobs", generation_config=None)
    config_path = directory / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    with (directory / "server.log").open("w") as log:
        process = subprocess.Popen(
            ["uv", "run", "--locked", "python", "-m", "server", "--config", str(config_path)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Server exited during startup; inspect startup server.log")
                    try:
                        response = client.get("/api/health")
                        break
                    except httpx.ConnectError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.1)
                response.raise_for_status()
                health = response.json()
                validate("Health", health)
                assert health["ok"] and not health["generation_available"]
                examples = client.get("/api/examples")
                examples.raise_for_status()
                for example in examples.json():
                    validate("Example", example)
                for file, mime in (
                    ("build/three.module.js", "text/javascript"),
                    ("examples/jsm/libs/draco/gltf/draco_decoder.wasm", "application/wasm"),
                ):
                    asset = client.get("/vendor/three/" + file)
                    asset.raise_for_status()
                    assert asset.headers["content-type"].startswith(mime)
                    assert len(asset.content) > 100
                report = {"port": port, "health": health, "examples": len(examples.json()), "vendor_js_wasm": "passed", "generation_attempted": False}
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError("Server did not shut down within 10 seconds") from None
    # Uvicorn re-raises SIGTERM after graceful shutdown; uv may encode it as 128 + signal.
    assert process.returncode in (0, -signal.SIGTERM, 128 + signal.SIGTERM)
    assert "Application shutdown complete." in (directory / "server.log").read_text()
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0, "Test server is still listening"
    report["exit_code"] = process.returncode
    report["server_stopped"] = True
    (directory / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
