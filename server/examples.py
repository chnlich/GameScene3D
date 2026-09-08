import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from server.files import SCHEMA, contained_file, public_safe, validate
from server.runtime import TaskError


def examples(root: Path):
    catalog_path = root / SCHEMA["x-demo"]["source_catalog"]
    if not catalog_path.exists():
        return []
    catalog_path = contained_file(root, SCHEMA["x-demo"]["source_catalog"])
    catalog = json.loads(catalog_path.read_text())
    if not isinstance(catalog, list):
        raise ValueError("Materials catalog must be an array")
    output = []
    for entry in catalog:
        path = contained_file(catalog_path.parent, entry["file"])
        if entry["generated_scene"] is not None:
            raise TaskError(503, "scene_metadata_unavailable", "Completed scene catalog mapping needs the materials scene metadata handoff; ask engineering to integrate that mapping.")
        example = {
            key: entry[key] for key in ("title", "source", "license", "license_url", "attribution", "changes")
        }
        example.update(
            id=hashlib.sha256(entry["file"].encode()).hexdigest()[:24],
            kind="input",
            description=f"{entry['category']}：{entry['visible_checks']}",
            input={"prompt": "", "image_url": "/demo/" + quote(path.relative_to(root / "demo").as_posix(), safe="/")},
        )
        validate("Example", example)
        public_safe(example)
        output.append(example)
    return output
