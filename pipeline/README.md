# GameFrame3D generation

`pipeline.runner.generate(request, output_dir, on_progress)` reconstructs an image,
optional accompanying text, or a text-only description. The repository's
`contracts/scene.schema.json` is the public interface. The internal scene is
validated in `models.py` and interpreted by Blender; model output is never executed
as Python. The viewer consumes the public result, not the manifest.

The configured inference backend identifies assets, reference crops, pose goals,
environment, lighting and a source camera. Meshy generates independent assets
concurrently; text assets run preview then refine, and articulated assets then run
rigging. Blender composes and renders the scene. The backend inspects the preview
with the original input and returns actual corrections. Inspection explicitly names
assets to regenerate; edits to transforms, pose and lighting reuse the measured mesh.
Accepted scenes are exported and reopened in another Blender
process before returning success. Failed reconstructions keep their artifacts.

## Run

Engineering owns root dependencies and the service launcher. This package needs
Python with Pydantic 2, PyYAML, Pillow and jsonschema, Blender with glTF
import/export, and Meshy access. Inference runs on the backend selected by the
required `inference_backend` setting; there is no default. The `codex` backend uses
an authenticated local Codex CLI with the package's existing host authentication
and no OpenAI API key. The `glm` backend posts OpenAI-compatible chat completions
to the configured intranet GLM gateway, with base64 image input and `json_schema`
structured output; the gateway needs no key. Setting `enable_thinking: false`
passes `chat_template_kwargs.enable_thinking: false` so responses return the
schema-constrained content directly instead of spending the token budget on
reasoning, while `true` (the default) preserves the gateway's reasoning output.
Numeric bound keywords (`minimum`, `maximum` and their exclusive variants) are
stripped from the GLM wire schema because the gateway's structured decoder
mishandles them; correctness is enforced by pydantic validation after the call.
Copy `config.example.yaml`
to private local storage and set explicit executable and owner-only key-file paths.
`pipeline.runner.preflight(config_path)` returns public-safe local readiness
reasons, or `[]` when configuration, executables, key-file and backend checks pass:
the codex backend checks host login, the glm backend checks that the configured
gateway answers and lists the configured model. Neither readiness pass runs
inference, paid requests or remote mutations. `generate` additionally
checks actual inference and the configured Meshy endpoint before generation.

```sh
python -m pipeline --config /private/config.yaml --output /private/jobs/image \
  --id image --image /private/input.png --prompt-file /private/image-prompt.txt
python -m pipeline --config /private/config.yaml --output /private/jobs/text \
  --id text --prompt-file /private/text-prompt.txt
```

Image-only use omits `--prompt-file`. Prompt files are read verbatim. Use a distinct
output directory for each input. Repeat the same command to reuse content-addressed
analysis (scoped to the configured inference backend, so cached analyses never cross
backends or model settings) and acknowledged Meshy submissions; inference calls and
rendering attempts have separate directories. A resumed call derives its scene from
the latest complete composition and inspects it again. When the first composition of
a run is unchanged — the scene, assets, Blender settings and composing implementation
all match a previously rendered iteration — that iteration's retained artifacts are
reopened instead of rendered again, and the reuse is recorded in the evidence. Provider responses and poll
histories preserve task IDs, status, consumption and timing. An unacknowledged
charged submission blocks reuse until reconciled with the provider; it is never
automatically reposted. HTTP 429 responses use bounded backoff and honor Retry-After
within the overall deadline.

Reopen an existing iteration independently when inference is unavailable:

```sh
python -m pipeline --config /private/config.yaml --output /private/jobs/image \
  --id image-readback --verify-iteration iterations/attempt/0
```

This operation reads the retained Blender project and GLB in a fresh process,
checks geometry and materials, and renders `verification/<id>/reopen.png` from
the scene camera. It makes no model or provider calls and does not mark visual
quality accepted. The reopened iteration's comparison preview is refreshed
beside it. Its invocation, report and logs remain beside the job.

Spending caps apply per output directory. To authorize unlimited spending, set
`spending.authorization` to an explicit authorization description,
`unlimited_authorized: true`, and both `max_credits` and `max_submissions` to `null`.
Numeric limits remain supported. Conservative per-call bounds reserve a capped
credit budget. Credits and account token counts are recorded separately; unknown
USD cost remains null.

## Evidence and geometry

The job retains original input, analyses, reference crops, sanitized provider
receipts, per-call inference evidence (sanitized request, raw response, usage and
timing) under `inference/`, iteration descriptions, previews, applied changes
and geometric checks. Successful artifacts include packed `scene.blend`, embedded
`scene.glb`, `preview.png`, `manifest.json` and `evidence.json`. Public paths are
relative to the output directory; only the service resolves URLs. Keep private
configuration outside that directory.
Image iterations also retain `comparison.png`, showing the source and generated
preview at the same aspect ratio, labeled as pending inspection.

Imported Meshy assets are aligned from glTF +Z front (Blender -Y) to the
internal +Y-facing convention before the analyzed transform is applied.
Internal geometry uses Blender Z-up meters. Blender exports with glTF Y-up, and
`Camera.gltf()` applies the same `(x, y, z) -> (x, z, -y)` conversion to camera
position, target and up. Source aspect comes from decoded image dimensions;
text-only aspect comes from the generated composition. Projection and normalized
observed landmarks come from scene analysis, with measured reprojection errors.

Models above the staging rigging face limit are remeshed to the configured
polygon target before rigging; the original textured model remains the final
surface source. Staging v2 remesh submissions return a task object, and the
verified v1 read representation supplies download URLs for the same task ID.
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
