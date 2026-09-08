import hashlib
import json
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from server.files import SCHEMA, contained_file, public_safe, publish_result, validate


def demo_reference(demo_root: Path, catalog_parent: Path, reference: str) -> str:
    """Resolve catalog-relative files within demo without traversing symlinks."""
    parsed = urlsplit(reference)
    if (
        not reference or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
        or reference.startswith("/") or "\\" in reference or unquote(reference) != reference
        or ":" in reference
    ):
        raise ValueError("Catalog asset must be a relative file")
    current = catalog_parent
    for part in PurePosixPath(reference).parts:
        current = current.parent if part == ".." else current / part
        if not current.is_relative_to(demo_root) or current.is_symlink():
            raise ValueError("Catalog asset escapes demo or traverses a symlink")
    relative = current.relative_to(demo_root).as_posix()
    contained_file(demo_root, relative)
    return relative


def examples(root: Path):
    catalog_path = root / SCHEMA["x-demo"]["source_catalog"]
    if not catalog_path.exists():
        return []
    catalog_path = contained_file(root, SCHEMA["x-demo"]["source_catalog"])
    demo_root = root.resolve() / "demo"
    catalog = json.loads(catalog_path.read_text())
    if not isinstance(catalog, list):
        raise ValueError("Materials catalog must be an array")
    output = []
    for entry in catalog:
        example = {
            key: entry[key] for key in ("title", "source", "license", "license_url", "attribution", "changes")
        }
        if entry["file"] is None:
            example.update(
                id=hashlib.sha256(entry["prompt"].encode()).hexdigest()[:24],
                kind="input",
                description=f"{entry['category']}: {entry['visible_checks']}",
                input={"prompt": entry["prompt"], "image_url": None},
            )
        else:
            reference = demo_reference(demo_root, catalog_path.parent, entry["file"])
            example.update(
                id=hashlib.sha256(entry["file"].encode()).hexdigest()[:24],
                kind="input",
                description=f"{entry['category']}: {entry['visible_checks']}",
                input={"prompt": "", "image_url": "/demo/" + quote(reference, safe="/")},
            )
        validate("Example", example)
        public_safe(example)
        output.append(example)
        result = entry["generated_scene"]
        if result is not None:
            validate("Result", result)
            result = {
                **result,
                "artifacts": {
                    role: demo_reference(demo_root, catalog_path.parent, path) if path is not None else None
                    for role, path in result["artifacts"].items()
                },
            }
            result = publish_result(result, demo_root, "/demo/")
            scene_id = example["id"] + "-scene"
            scene = {
                key: entry[key] for key in ("source", "license", "license_url", "attribution", "changes")
            }
            scene.update(
                id=scene_id,
                title=result["title"],
                description=result["summary"],
                kind="scene",
                prerecorded=True,
                job={
                    "id": scene_id,
                    "status": "succeeded",
                    "progress": {"phase": "prerecorded", "message": result["summary"], "fraction": 1},
                    "input": example["input"],
                    "result": result,
                    "error": None,
                },
            )
            validate("Example", scene)
            public_safe(scene)
            output.append(scene)
    return output
