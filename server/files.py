import json
import os
import re
import struct
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts/scene.schema.json").read_text())
Draft202012Validator.check_schema(SCHEMA)


def validate(kind: str, value):
    Draft202012Validator(
        {**SCHEMA, "$ref": f"#/$defs/{kind}"}, format_checker=FormatChecker()
    ).validate(value)
    # JSON Schema treats NaN as a number; JSON on disk and HTTP must not.
    json.dumps(value, allow_nan=False)


def atomic_json(path: Path, value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    atomic_bytes(path, data)


def atomic_bytes(path: Path, data: bytes):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def contained_file(root: Path, reference: str) -> Path:
    parsed = urlsplit(reference)
    parts = PurePosixPath(reference).parts
    if (
        not reference or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
        or reference.startswith("/") or "\\" in reference or unquote(reference) != reference
        or ".." in parts or ":" in reference
    ):
        raise ValueError("Artifact must be a relative contained file")
    if root.is_symlink():
        raise ValueError("Symlink roots are not public")
    root = root.resolve(strict=True)
    candidate = root / reference
    # Refuse even internal symlinks, keeping the public namespace unambiguous.
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink artifacts are not public")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("Artifact is not a contained regular file")
    return resolved


_PRIVATE_TEXT = re.compile(
    r"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|(?<![\w:/])/(?!demo/|artifacts/|vendor/three/)\S+"
    r"|\b(?:sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+)|(?:api[_-]?key|password|secret|token)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)

_PRIVATE_KEYS = re.compile(r"^(?:api[_-]?key|access[_-]?token|password|secret|credentials|authorization)$", re.I)


def public_safe(value):
    """Reject common secret and host-path disclosures before publication."""
    if isinstance(value, str) and _PRIVATE_TEXT.search(value):
        raise ValueError("Private data in public output")
    if isinstance(value, dict):
        for key, item in value.items():
            if _PRIVATE_KEYS.match(key) and item is not None:
                raise ValueError("Credential field in public output")
            public_safe(key)
            public_safe(item)
    elif isinstance(value, list):
        for item in value:
            public_safe(item)


def verify_glb(path: Path):
    data = path.read_bytes()
    if len(data) < 20 or struct.unpack_from("<4sII", data) != (b"glTF", 2, len(data)):
        raise ValueError("Invalid GLB header")
    offset = 12
    chunks = []
    while offset < len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if length % 4 or offset + length > len(data):
            raise ValueError("Invalid GLB chunk")
        chunks.append((kind, data[offset:offset + length]))
        offset += length
    if not chunks or chunks[0][0] != 0x4E4F534A:
        raise ValueError("GLB must start with JSON")
    scene = json.loads(chunks[0][1])
    if scene["asset"]["version"] != "2.0" or not scene.get("scenes") or not scene.get("nodes"):
        raise ValueError("GLB has no scene")
    for collection in ("buffers", "images"):
        for item in scene.get(collection, []):
            if "uri" in item and not item["uri"].startswith("data:"):
                raise ValueError("GLB must embed its resources")
    buffers = scene.get("buffers", [])
    if buffers and "uri" not in buffers[0]:
        if len(chunks) != 2 or chunks[1][0] != 0x004E4942 or len(chunks[1][1]) < buffers[0]["byteLength"]:
            raise ValueError("GLB binary buffer is incomplete")
    public_safe(scene)


def publish_result(result: dict, root: Path, prefix: str) -> dict:
    validate("Result", result)
    public_safe(result)
    result = json.loads(json.dumps(result))
    for role, reference in result["artifacts"].items():
        if reference is None:
            continue
        if reference in ("job.json", "request.json", "result.json", ".owner.lock"):
            raise ValueError("Internal job records are not artifacts")
        path = contained_file(root, reference)
        if path.stat().st_size == 0:
            raise ValueError("Empty artifact")
        if role == "glb":
            verify_glb(path)
        elif role == "evidence":
            evidence = json.loads(path.read_text())
            if not isinstance(evidence, dict) or not evidence:
                raise ValueError("Evidence must be a nonempty JSON object")
            public_safe(evidence)
        elif role in ("preview", "original"):
            with Image.open(path) as image:
                image.verify()
        elif role == "manifest":
            public_safe(json.loads(path.read_text()))
        result["artifacts"][role] = prefix + quote(reference, safe="/")
    validate("Result", result)
    return result
