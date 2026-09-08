"""Freeze the public viewer and validated catalog for static hosting."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

from server.examples import examples
from server.files import ROOT, SCHEMA, contained_file, public_safe, validate


def export(output: Path):
    if output.is_symlink():
        raise ValueError("Output must not be a symlink")
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"Output already contains data: {output}")
    for source in (ROOT / "web", ROOT / "demo", ROOT / "node_modules/three"):
        if output.is_relative_to(source.resolve()):
            raise ValueError("Output must be outside public source directories")

    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "web/", "demo/"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout.decode().split("\0")
    files = {name: contained_file(ROOT, name) for name in tracked if name}
    files["index.html"] = files["web/index.html"]
    files["contracts/scene.schema.json"] = contained_file(ROOT, "contracts/scene.schema.json")
    for name in (SCHEMA["x-demo"]["source_catalog"], SCHEMA["x-demo"]["source_attribution"]):
        files[name]  # Required public provenance must be tracked and present.

    package = json.loads(contained_file(ROOT, "node_modules/three/package.json").read_text())
    required = json.loads((ROOT / "package.json").read_text())["dependencies"]["three"]
    if package["name"] != "three" or package["version"] != required:
        raise ValueError("Installed three does not match package.json; run npm ci")
    vendor = ROOT / "node_modules/three"
    for path in sorted(vendor.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink in three package: {path}")
        if not path.is_dir():
            name = path.relative_to(vendor).as_posix()
            files["vendor/three/" + name] = contained_file(ROOT, "node_modules/three/" + name)

    catalog = examples(ROOT)
    for example in catalog:
        record = example["input"] if example["kind"] == "input" else example["job"]["input"]
        urls = [record["image_url"]]
        if example["kind"] == "scene":
            urls.extend(example["job"]["result"]["artifacts"].values())
        for url in urls:
            if url is not None and unquote(url.removeprefix("/")) not in files:
                raise ValueError(f"Example asset is not in the export: {url}")
    health = {
        "ok": True,
        "generation_available": False,
        "generation_note": "静态展示快照，仅供查看已完成场景；生成服务仅在本地运行，此站点不提供生成接口。",
    }
    validate("Health", health)
    public_safe(health)

    output.mkdir(parents=True, exist_ok=True)
    for name, source in sorted(files.items()):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as reader, target.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
    (output / "api").mkdir()
    for name, value in (("examples", catalog), ("health", health)):
        with (output / "api" / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    size = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    print(f"Exported {len(catalog)} examples, {len(files) + 2} files, {size} bytes to {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New or empty export directory")
    args = parser.parse_args()
    export(args.output)


if __name__ == "__main__":
    main()
