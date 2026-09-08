# GameFrame3D viewer

The first screen displays completed GLBs beside their original images. The first
successful examples load opens the first scene only if the user has not started
an input or scene operation; refreshing the list never changes that selection.
Scene cards retain prerecorded labels and API-provided provenance. An empty scene
list explicitly says no completed scene has been published.

The collapsed production tools contain image/text submission, candidate inputs,
service health, job progress, and status retries. Generation health does not gate
completed scene viewing. Input examples only prepare a submission.

Serve `index.html` at `/` and this directory at `/web/`. The bootstrap reads the
engineering-owned `/contracts/scene.schema.json` and installs the `x-web` import
map before importing the viewer. The server must expose that contract read-only
and serve the vendor resources named by it. Dependencies, installation, and
service launch belong to the root engineering entry point; this directory has
no separate package manifest, lockfile, backend, or build step.

`app.mjs` owns input selection, API requests, job observation, and presentation.
Changing input stops observation of the previous job; it does not cancel work
on the server. Failed status reads expose an explicit retry for the existing
job. API errors, failed generation, and scene loading errors have separate UI.
`viewer.mjs` owns Three.js resources and camera controls. It applies the contract
camera in unchanged GLB world coordinates, uses decoded original image dimensions
for letterboxing, and preserves the camera on resize. Missing cameras receive a
clearly labeled default view. Manifest is offered only as a download.

Integration requires the real jobs, examples, health, artifacts, and demo
endpoints defined by the shared contract. Check image and text submissions,
server success and failure, both example types, provenance, downloadable bytes,
Draco rendering, camera reset for both projections, image proportions, default
camera wording, stale request handling, and narrow screens on that service.
Capture browser console/page errors and screenshots using the allocated muted
browser instance, closing it after the run. Module syntax checks alone do not
establish that these integration requirements pass.
