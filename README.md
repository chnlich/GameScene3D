# GameFrame3D

GameFrame3D turns image and text inputs into 3D scenes with downloadable generation
evidence. This checkout supplies the HTTP/runtime foundation; the independent
`pipeline/`, `web/` and `demo/` work lines supply generation, the viewer and materials.
`contracts/scene.schema.json` is the sole shared HTTP and Python contract. The server
loads its definitions at runtime; it does not maintain an OpenAPI or Pydantic copy.

Run from the repository root with Python 3.11+, uv and npm installed:

```sh
uv sync --locked
npm ci
uv run python -m server --config config.example.yaml
```

The example binds to `127.0.0.1:8765`. Copy it to `config.yaml` to select another
host/port, isolated data directory, generation YAML path, execution/queue capacity,
upload/request byte limits, prompt length and decoded image pixel limit. Paths
resolve relative to the root YAML file. Pydantic rejects unknown keys and invalid
limits. Keep credentials in the pipeline's own local configuration, outside public
assets; root configuration contains only its explicit path. Generation YAML parsing
and validation belong to pipeline.

`GET /api/health` separates HTTP liveness from generation capability. The adapter
requires callable `pipeline.runner.generate` and `pipeline.runner.preflight`, then
calls `preflight(config_path: str | None) -> list[str]` with the same resolved path
(or null) used for generation. Start generation configuration from
`pipeline/config.example.yaml`; pipeline owns executable, login, provider and
spending configuration semantics. Explicit unlimited spending is supported without
a numeric cap or another approval. Root does not duplicate those rules.

Preflight returns safe blocking reasons, with no credentials or private paths.
Invalid returns and exceptions fail capability with a generic public reason and
local diagnostic log. Blocking reasons make submissions return `503 Error`.
An empty list means local prerequisites only. Preflight must be read-only, with no
model calls, charged requests or external modifications. A working model CLI probe,
HTTP liveness and successful full scene generation are separate readiness claims.

Submit multipart `image` (actual PNG/JPEG/WebP) and/or a nonempty `prompt` to
`POST /api/jobs`. Accepted requests return `202 Job`; invalid inputs return
`422 Error`; a full execution/queue limit returns `503 Error` with code `busy`.
Poll `GET /api/jobs/{id}`. The adapter calls exactly
`pipeline.runner.generate(request, output_dir, on_progress)` in a bounded thread
pool. The request carries the explicit generation configuration path. Inputs are
never interpolated into shell commands. Progress callbacks and final results must
validate against the shared contract.

Each opaque job directory retains original bytes, safe request metadata, atomic
job snapshots and final result metadata. Pipeline evidence and partial files remain
after failure. A data-directory OS lock allows one live server owner. On restart,
queued/running snapshots from the previous owner become failed; the server does
not retry work automatically. Graceful shutdown waits for accepted jobs to finish.
A running call must return or raise before its execution slot is released.

Successful publication requires a contained GLB with readable glTF 2.0 JSON and
embedded resources, a nonempty JSON evidence object, and readable declared image
artifacts. This structural check is not a renderer or visual-quality assessment.
The adapter checks source-image camera aspect and measures actual execution time.
It maps declared artifact paths to `/artifacts/{id}/` URLs; only those files and
retained input are downloadable. Missing or invalid final files invalidate success.
Raw exception details stay in server logs. Common credential fields and local path
leaks are rejected from public output; pipeline remains responsible for sanitizing
provider evidence and packed binary assets before returning them.

`GET /api/examples` derives provenance from the materials-owned catalog at the path
specified by `x-demo`. The inspected materials handoff is an array with `file`,
`title`, `category`, `visible_checks`, provenance fields, and `generated_scene`.
Files resolve relative to `demo/materials/catalog.json`. Null `generated_scene`
entries expose candidate inputs; non-null results also expose validated prerecorded
scenes. The current catalog includes a reused scene with prior-generation and
manual-pose provenance. Unknown historical timing, cost and unverified source-image
camera remain null. No catalog means an empty list in the live API; malformed
catalog data fails visibly.

For public delivery of the completed-demo viewer, export a display-only snapshot
after the dependency installation above, from a Git checkout with Git installed:

```sh
uv run python -m server.export --output runtime/static-demo
python -m http.server 8080 --bind 127.0.0.1 --directory runtime/static-demo
```

Choose a new or empty output directory; export refuses existing data and never
deletes it. The exporter copies the current tracked `web/` and sanitized `demo/`
files, the exact canonical contract, and only the installed three package to
`/vendor/three/`. It freezes `server.examples.examples(ROOT)` into the static file
`api/examples` and writes `api/health` with generation unavailable. These are JSON
files read by the viewer, not a backend; no POST endpoint is published. Existing
viewer production controls cannot generate here. Actual live generation remains
local through the server command above. Host the output at a dedicated hostname's
root: root-relative URLs do not support GitHub project subpaths. Export and the
loopback preview command do not publish the site publicly.

`GET /contracts/scene.schema.json` serves the canonical file as `application/json`.
Viewer bootstrap dynamically reads `x-web.import_map` there. Other contracts paths
return 404 and never enter viewer fallback. Read-only `/demo/` serves materials. `/vendor/three/` serves only the installed
contract-pinned three package, including JS modules and WASM Draco assets.
`web/index.html` and viewer modules are served when installed; otherwise the root
reports `ui_not_ready`. API and asset routes take precedence. Traversal and symlinks,
including symlink asset directories, are rejected.

For integration readback, start the real server through the CLI above and inspect
`/api/health`, `/contracts/scene.schema.json`, `/api/examples`, `/`, and the contract's
Three.js module and Draco decoder URLs. Compare contract bytes with the repository
file and check JS/WASM MIME types. Stop only the server started for the check.
Keep command and log evidence under ignored `runtime/`, outside public assets.

Existing `server/tests/` files are retained as historical offline plumbing evidence.
Their capability checks predate pipeline-owned preflight; they were not rerun or
updated for this integration review. Offline GLBs do not prove model generation.
Full pipeline integration and viewer/browser verification
remain separate integration dependencies.

| Work line | Owned files | Branch |
| --- | --- | --- |
| Engineering | Root runtime/configuration/locks, `server/`, shared `contracts/` | `work/engineering` |
| Generation | `pipeline/` | `work/generation` |
| Viewer | `web/` | `work/viewer` |
| Materials | `demo/` | `work/demo` |
