import { Viewer } from './viewer.mjs';
import { requestJSON, safeURL, cameraNote, CONTROLS_NOTE } from './presentation.mjs';
import { originalPane, provenanceList, assumptionsBlock, entryFoot } from './entry-view.mjs';

const $ = id => document.getElementById(id);

function stageFail(message) {
  const status = $('stage-status');
  status.hidden = false;
  status.classList.add('error');
  status.textContent = message;
}

function fail(message) {
  console.error(message);
  const pageError = $('page-error');
  pageError.hidden = false;
  pageError.textContent = message;
  if ($('stage')) stageFail(message);
}

export async function start(config) {
  const id = new URLSearchParams(location.search).get('id');
  if (id === null) return fail('No scene id in the address. Open a scene from the created-scenes gallery.');

  let examples;
  try {
    examples = await requestJSON('/api/examples');
  } catch (error) {
    return fail('Failed to load the scene list: ' + error.message);
  }
  const example = examples.find(candidate => candidate.id === id);
  if (example === undefined) return fail(`No published entry has id “${id}”.`);
  if (example.kind !== 'scene') return fail('That entry is not a 3D scene.');
  if (example.prerecorded !== true) return fail('Scene example is not marked prerecorded');
  if (example.job.status !== 'succeeded') return fail('Scene example does not contain a succeeded job');
  const result = example.job.result;
  if (!result.artifacts.glb) return fail('This scene has no published GLB artifact.');

  $('scene-title').textContent = example.title;
  $('scene-desc').textContent = example.description;
  const pane = originalPane(example, result);
  $('original-slot').append(pane.figure);
  $('provenance-slot').append(provenanceList(example));
  $('assumptions-slot').append(assumptionsBlock(result));
  $('foot-slot').append(entryFoot(result));

  const stage = $('stage');
  const viewer = new Viewer(stage, config.draco_decoder_path, error => {
    console.error(error);
    stageFail(error.message);
  });
  viewer.attach(stage);
  window.addEventListener('pagehide', () => viewer.dispose(), { once: true });

  let aspect = null;
  const img = pane.originalImg;
  if (img) {
    const decoded = img.decode().catch(error => console.info('Original image decode failed:', error));
    await Promise.race([decoded, new Promise(resolve => setTimeout(resolve, 1500))]);
    aspect = img.naturalWidth > 0 ? img.naturalWidth / img.naturalHeight : null;
  }

  try {
    await viewer.load(safeURL(result.artifacts.glb), result.camera, aspect);
  } catch (error) {
    console.error(error);
    stageFail('Failed to load the 3D scene: ' + error.message);
    return;
  }

  $('stage-status').hidden = true;
  const resetButton = $('reset-view');
  resetButton.hidden = false;
  resetButton.textContent = result.camera === null ? 'Reset default view' : 'Reset source camera';
  $('view-note').textContent = cameraNote(result.camera) + CONTROLS_NOTE;
  resetButton.addEventListener('click', () => viewer.reset());
}
