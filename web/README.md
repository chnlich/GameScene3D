# GameFrame3D viewer

The showcase has two English pages. The landing page (`index.html`, served at
`/`) is the Created Scenes gallery: it lists every prerecorded scene example
with the original input image beside a preview, and a click-to-load lazy 3D
embed per scene. One shared Three.js viewer is created on demand, moved between
entries, and only one scene stays resident at a time; closing an entry or
loading another one disposes the previous model. Scene cards render the API
provenance fields as-is under English labels, list the recorded assumptions,
and label a null camera as the default view, never the original camera. An
empty scene list explicitly says no created scene has been published.

`studio.html` (served at `/web/studio.html`) is the Interactive Studio: the
workspace displays a completed GLB beside its original image, the examples
lists, and the collapsed production tools with image/text submission, candidate
inputs, service health, job progress, and status retries. Generation health
does not gate completed scene viewing. Input examples only prepare a
submission. The first successful examples load opens the first scene only if
the user has not started an input or scene operation; refreshing the list never
changes that selection.

Serve `index.html` at `/`, this directory at `/web/`, and the shared modules
read `document.body.dataset.page` to dispatch between the gallery and the
studio. The bootstrap reads the engineering-owned
`/contracts/scene.schema.json` and installs the `x-web` import map before
importing the viewer. The server must expose that contract read-only and serve
the vendor resources named by it. Dependencies, installation, and service
launch belong to the root engineering entry point; this directory has no
separate package manifest, lockfile, backend, or build step.

`gallery.mjs` owns the created-scenes page. `app.mjs` owns input selection,
API requests, job observation, and presentation on the studio page. Changing
input stops observation of the previous job; it does not cancel work on the
server. Failed status reads expose an explicit retry for the existing job. API
errors, failed generation, and scene loading errors have separate UI.
`viewer.mjs` owns Three.js resources and camera controls. It applies the
contract camera in unchanged GLB world coordinates, uses decoded original image
dimensions for letterboxing, and preserves the camera on resize. Missing
cameras receive a clearly labeled default view. Manifest is offered only as a
download.

Integration requires the real jobs, examples, health, artifacts, and demo
endpoints defined by the shared contract. Check image and text submissions,
server success and failure, both example types, provenance, downloadable bytes,
Draco rendering, camera reset for both projections, image proportions, default
camera wording, stale request handling, gallery lazy loading and switching on
both pages, and narrow screens on that service. Capture browser console/page
errors and screenshots using the allocated muted browser instance, closing it
after the run. Module syntax checks alone do not establish that these
integration requirements pass.
