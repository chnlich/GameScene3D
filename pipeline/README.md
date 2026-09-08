# GameFrame3D generation

`pipeline.runner.generate(request, output_dir, on_progress)` reconstructs an image,
optional accompanying text, or a text-only description. The repository's
`contracts/scene.schema.json` is the public interface. The internal scene is
validated in `models.py` and interpreted by Blender; model output is never executed
as Python. The viewer consumes the public result, not the manifest.

Astra identifies assets, reference crops, pose goals, environment, lighting and a
source camera. Meshy generates independent assets concurrently; text assets run
preview then refine, and articulated assets then run rigging. Blender composes and
renders the scene. Astra inspects the preview with the original input and returns
actual corrections. Accepted scenes are exported and reopened in another Blender
process before returning success. Failed reconstructions keep their artifacts.

## Run

Engineering owns root dependencies and the service launcher. This package needs
Python with Pydantic 2, PyYAML, Pillow and jsonschema, an authenticated local Codex
CLI, Blender with glTF import/export, and Meshy access. Copy `config.example.yaml`
to private local storage and set explicit executable and owner-only key-file paths.
The package uses existing Codex authentication on the host. It does not use an
OpenAI API key. `pipeline.runner.preflight(config_path)` returns public-safe local readiness
reasons, or `[]` when configuration, executables, host login and key-file checks
pass. It does not run inference or make provider requests. `generate` additionally
checks actual Astra inference and the configured Meshy endpoint before generation.

```sh
python -m pipeline --config /private/config.yaml --output /private/jobs/image \
  --id image --image /private/input.png --prompt-file /private/image-prompt.txt
python -m pipeline --config /private/config.yaml --output /private/jobs/text \
  --id text --prompt-file /private/text-prompt.txt
```

Image-only use omits `--prompt-file`. Prompt files are read verbatim. Use a distinct
output directory for each input. Repeat the same command to reuse content-addressed
analysis and acknowledged Meshy submissions; inference calls and rendering attempts
have separate directories. Provider responses and poll histories preserve task IDs,
status, consumption and timing. An unacknowledged charged submission blocks reuse
until reconciled with the provider; it is never automatically reposted. HTTP 429
responses use bounded backoff and honor Retry-After within the overall deadline.

Spending caps apply per output directory. To authorize unlimited spending, set
`spending.authorization` to an explicit authorization description,
`unlimited_authorized: true`, and both `max_credits` and `max_submissions` to `null`.
Numeric limits remain supported. Conservative per-call bounds reserve a capped
credit budget. Credits and account token counts are recorded separately; unknown
USD cost remains null.

## Evidence and geometry

The job retains original input, analyses, reference crops, sanitized provider
receipts, inference events/usage, iteration descriptions, previews, applied changes
and geometric checks. Successful artifacts include packed `scene.blend`, embedded
`scene.glb`, `preview.png`, `manifest.json` and `evidence.json`. Public paths are
relative to the output directory; only the service resolves URLs. Keep private
configuration outside that directory.

Internal geometry uses Blender Z-up meters. Blender exports with glTF Y-up, and
`Camera.gltf()` applies the same `(x, y, z) -> (x, z, -y)` conversion to camera
position, target and up. Source aspect comes from decoded image dimensions;
text-only aspect comes from the generated composition. Projection and normalized
observed landmarks come from scene analysis, with measured reprojection errors.

Rig selection compares original and rigged textures and UVs. Differing materials
use original UV/PBR with transferred weights, retaining the original 3.5%-of-height
95th-percentile surface-distance rejection threshold. Pose targets and achieved
joint positions are measured. Export bakes evaluated geometry and retains source
rigs in the Blender project. Fresh-process reopening checks meshes, materials,
textures and composed bounds.

The image-to-3D transport, rig dependency, UV-preserving transfer, IK and static
export adapt the project's earlier manually composed Blender work. Character names,
source-specific poses and private host paths are not part of this implementation.
Relevant provider references: [Codex noninteractive mode](https://developers.openai.com/codex/noninteractive),
[Meshy image-to-3D](https://docs.meshy.ai/en/api/image-to-3d),
[text-to-3D](https://docs.meshy.ai/en/api/text-to-3d), and
[rigging](https://docs.meshy.ai/en/api/rigging).
