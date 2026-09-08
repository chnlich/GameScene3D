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
checks the explicit generation configuration, `codex` and `blender` executables on
PATH, and callable `pipeline.runner.generate`. Missing prerequisites produce a safe
unavailable reason and submissions return `503 Error`. Detected prerequisites do
not establish authentication, valid provider configuration or a working full 3D
pipeline. The previously verified local Codex image/structured-output probe also
does not establish full 3D generation. Health performs no model calls.

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
Current entries all have `generated_scene: null`; their files resolve relative to
`demo/materials/catalog.json`, and the API exposes candidate inputs. No catalog
means an empty list. Malformed catalog data fails visibly. Completed-scene catalog
metadata has not been supplied: a non-null `generated_scene` reports an integration
error instead of inventing a SceneExample. Engineering needs a narrow followup with
materials' actual sanitized scene mapping, including prior-generation/manual-pose
provenance and unknown historical timing. The current contract allows that timing
to be null; an unverified source-image camera remains null.

Read-only `/demo/` serves materials. `/vendor/three/` serves only the installed
contract-pinned three package, including JS modules and WASM Draco assets.
`web/index.html` and viewer modules are served when installed; otherwise the root
reports `ui_not_ready`. API and asset routes take precedence. Traversal and symlinks,
including symlink asset directories, are rejected.

Run the reproducible engineering checks:

```sh
uv run python -m server.tests.check
```

This recipe asserts launchers and locks, runs `uv sync --locked` and `npm ci`, checks
unchanged lockfiles, runs the explicitly labeled offline plumbing tests, and starts
and closes the real server via its CLI on an unused loopback port. Startup checks
health, examples and installed vendor JS/WASM without submitting generation. Reports
and service logs stay under `runtime/startup-*/`. Offline GLBs are test fixtures;
they are not user generation or proof of the model pipeline. No browser, production
service change or paid inference is involved. Full pipeline integration, materials
scene metadata, viewer/browser verification and engineering master's Astra review
remain separate integration dependencies.

| Work line | Owned files | Branch |
| --- | --- | --- |
| Engineering | Root runtime/configuration/locks, `server/`, shared `contracts/` | `work/engineering` |
| Generation | `pipeline/` | `work/generation` |
| Viewer | `web/` | `work/viewer` |
| Materials | `demo/` | `work/demo` |
