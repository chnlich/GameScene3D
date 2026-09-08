import { Viewer } from './viewer.mjs';
import { metrics, requestJSON, safeURL } from './presentation.mjs';

const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };

const CONTROLS_NOTE = ' Drag to rotate · scroll to zoom · right-drag to pan; touch: one finger rotates, two fingers zoom and pan.';
const IDLE_NOTE = ' Click “Load 3D view” to explore it here.';

function cameraNote(camera) {
  return camera === null
    ? 'Default view — no verified source-image camera exists for this prerecorded scene.'
    : 'Source-image camera applied in the GLB world coordinates.';
}

class Gallery {
  constructor(config) {
    this.config = config;
    this.token = 0;
    this.sequence = 0;
    this.request = new AbortController();
    this.viewer = null;
    this.active = null;
    this.states = new Map();
    $('reload-scenes').addEventListener('click', () => this.load());
    window.addEventListener('pagehide', () => {
      this.request.abort();
      this.closeViewer();
      this.viewer?.dispose();
    }, { once: true });
  }

  ensureViewer() {
    if (this.viewer === null) {
      this.viewer = new Viewer(document.createElement('div'), this.config.draco_decoder_path, error => this.viewerError(error));
    }
    return this.viewer;
  }

  viewerError(error) {
    console.error(error);
    const state = this.active;
    if (state) {
      this.closeViewer();
      state.errorLine.hidden = false;
      state.errorLine.textContent = error.message;
    }
  }

  closeViewer() {
    this.token += 1;
    const state = this.active;
    if (!state) return;
    this.active = null;
    state.live = false;
    state.resetButton.hidden = true;
    state.loadButton.disabled = false;
    state.loadButton.textContent = 'Load 3D view';
    state.sideLabel.textContent = 'Preview';
    state.viewport.hidden = true;
    state.status.classList.remove('error');
    if (state.previewImg) state.previewImg.hidden = false;
    state.note.textContent = cameraNote(state.camera) + IDLE_NOTE;
    if (this.viewer) {
      this.viewer.clear();
      this.viewer.detach();
    }
  }

  async open(entry) {
    this.closeViewer();
    const state = this.states.get(entry);
    const viewer = this.ensureViewer();
    const token = ++this.token;
    this.active = state;
    viewer.attach(state.host);
    state.viewport.hidden = false;
    if (state.previewImg) state.previewImg.hidden = true;
    state.sideLabel.textContent = 'Interactive 3D';
    state.status.classList.remove('error');
    state.status.hidden = false;
    state.status.textContent = 'Loading the 3D scene…';
    state.loadButton.disabled = true;
    state.errorLine.hidden = true;
    const original = state.originalImg;
    const aspect = original && original.complete && original.naturalWidth > 0
      ? original.naturalWidth / original.naturalHeight
      : null;
    try {
      const loaded = await viewer.load(safeURL(state.glb), state.camera, aspect);
      if (token !== this.token) {
        console.info('Superseded scene load finished');
        return;
      }
      if (!loaded) throw new Error('The scene was replaced before it finished loading.');
      state.status.hidden = true;
      state.resetButton.hidden = false;
      state.resetButton.disabled = false;
      state.loadButton.disabled = false;
      state.loadButton.textContent = 'Close 3D view';
      state.note.textContent = cameraNote(state.camera) + CONTROLS_NOTE;
      state.live = true;
    } catch (error) {
      if (token !== this.token) {
        console.info('Superseded scene load failed:', error.message);
        return;
      }
      console.error(error);
      this.closeViewer();
      state.errorLine.hidden = false;
      state.errorLine.textContent = `Failed to load the 3D scene: ${error.message}`;
    }
  }

  toggle(entry) {
    if (this.active?.entry === entry) this.closeViewer();
    else this.open(entry);
  }

  mediaFigure(caption) {
    const figure = document.createElement('figure');
    figure.className = 'media';
    const label = document.createElement('figcaption');
    label.textContent = caption;
    const body = document.createElement('div');
    body.className = 'media-body';
    figure.append(label, body);
    return { figure, label, body };
  }

  buildEntry(example) {
    if (example.prerecorded !== true) throw new Error('Scene example is not marked prerecorded');
    if (example.job.status !== 'succeeded') throw new Error('Scene example does not contain a succeeded job');
    const result = example.job.result;
    const entry = document.createElement('article');
    entry.className = 'scene-entry';

    const head = document.createElement('div');
    head.className = 'entry-head';
    const heading = document.createElement('div');
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = 'Prerecorded scene';
    const title = document.createElement('h3');
    title.textContent = example.title;
    const description = document.createElement('p');
    description.className = 'entry-desc';
    description.textContent = example.description;
    heading.append(tag, title, description);
    const actions = document.createElement('div');
    actions.className = 'entry-actions';
    const resetButton = document.createElement('button');
    resetButton.type = 'button';
    resetButton.hidden = true;
    resetButton.textContent = result.camera === null ? 'Reset default view' : 'Reset source camera';
    const loadButton = document.createElement('button');
    loadButton.type = 'button';
    loadButton.className = 'primary';
    loadButton.textContent = 'Load 3D view';
    actions.append(resetButton, loadButton);
    head.append(heading, actions);

    const media = document.createElement('div');
    media.className = 'entry-media';
    const originalPane = this.mediaFigure('Original input');
    let originalImg = null;
    if (result.artifacts.original) {
      originalImg = new Image();
      originalImg.alt = `Original input image for ${example.title}`;
      originalImg.src = safeURL(result.artifacts.original);
      originalImg.className = 'fill';
      originalImg.loading = 'lazy';
      originalPane.body.append(originalImg);
    } else {
      const empty = document.createElement('p');
      empty.className = 'media-empty';
      empty.textContent = 'No original image; this scene was created from a text prompt.';
      originalPane.body.append(empty);
    }
    const sidePane = this.mediaFigure('Preview');
    let previewImg = null;
    if (result.artifacts.preview) {
      previewImg = new Image();
      previewImg.alt = `Preview render for ${example.title}`;
      previewImg.src = safeURL(result.artifacts.preview);
      previewImg.className = 'fill';
      previewImg.loading = 'lazy';
      sidePane.body.append(previewImg);
    } else {
      const empty = document.createElement('p');
      empty.className = 'media-empty';
      empty.textContent = 'No preview was published for this scene.';
      sidePane.body.append(empty);
    }
    const viewport = document.createElement('div');
    viewport.className = 'viewport';
    viewport.hidden = true;
    const status = document.createElement('p');
    status.className = 'viewport-status';
    status.textContent = 'Loading the 3D scene…';
    const host = document.createElement('div');
    host.className = 'canvas-host';
    viewport.append(status, host);
    sidePane.body.append(viewport);
    media.append(originalPane.figure, sidePane.figure);

    const note = document.createElement('p');
    note.className = 'view-note';
    note.textContent = cameraNote(result.camera) + IDLE_NOTE;
    const errorLine = document.createElement('p');
    errorLine.className = 'error entry-error';
    errorLine.hidden = true;

    const provenance = document.createElement('dl');
    provenance.className = 'entry-provenance';
    for (const [key, label] of [['source', 'Source'], ['license', 'License'], ['attribution', 'Attribution'], ['changes', 'Changes']]) {
      const term = document.createElement('dt');
      term.textContent = label;
      const value = document.createElement('dd');
      value.textContent = example[key];
      provenance.append(term, value);
    }
    if (example.license_url) {
      const link = document.createElement('a');
      link.href = safeURL(example.license_url);
      link.textContent = 'License terms';
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      const value = document.createElement('dd');
      value.append(link);
      provenance.append(value);
    }

    const assumptionsWrap = document.createElement('div');
    assumptionsWrap.className = 'entry-assumptions';
    const assumptionsHead = document.createElement('h4');
    assumptionsHead.textContent = 'Assumptions';
    const assumptionsList = document.createElement('ul');
    if (result.assumptions.length === 0) {
      const item = document.createElement('li');
      item.textContent = 'None recorded.';
      assumptionsList.append(item);
    } else {
      for (const assumption of result.assumptions) {
        const item = document.createElement('li');
        item.textContent = assumption;
        assumptionsList.append(item);
      }
    }
    assumptionsWrap.append(assumptionsHead, assumptionsList);

    const foot = document.createElement('div');
    foot.className = 'entry-foot';
    const metricsLine = document.createElement('p');
    metricsLine.textContent = metrics(result);
    const downloads = document.createElement('nav');
    downloads.className = 'downloads';
    downloads.setAttribute('aria-label', 'Scene downloads');
    for (const [key, label] of [['glb', 'Download GLB'], ['blend', 'Blender project'], ['manifest', 'Manifest'], ['evidence', 'Generation evidence']]) {
      if (result.artifacts[key]) {
        const link = document.createElement('a');
        link.href = safeURL(result.artifacts[key]);
        link.download = '';
        link.textContent = label;
        downloads.append(link);
      }
    }
    foot.append(metricsLine, downloads);

    entry.append(head, media, note, errorLine, provenance, assumptionsWrap, foot);
    const state = {
      entry, loadButton, resetButton, sideLabel: sidePane.label, previewImg, viewport, status, host,
      note, errorLine, originalImg,
      glb: result.artifacts.glb,
      camera: result.camera,
      live: false,
    };
    this.states.set(entry, state);
    loadButton.addEventListener('click', () => this.toggle(entry));
    resetButton.addEventListener('click', () => this.viewer?.reset());
    return entry;
  }

  async load() {
    const sequence = ++this.sequence;
    this.request.abort();
    this.request = new AbortController();
    text('scenes-status', 'Loading created scenes…');
    try {
      const examples = await requestJSON('/api/examples', { signal: this.request.signal });
      if (sequence !== this.sequence) return;
      const scenes = [];
      for (const example of examples) {
        if (example.kind === 'scene') scenes.push(example);
        else if (example.kind !== 'input') throw new Error(`Unknown example kind: ${example.kind}`);
      }
      this.closeViewer();
      this.states.clear();
      $('scenes').replaceChildren(...scenes.map(example => this.buildEntry(example)));
      text('scenes-status', scenes.length === 0
        ? 'No created scenes have been published yet. The Interactive Studio can generate new ones.'
        : 'Click “Load 3D view” on an entry to explore the scene beside its original input.');
    } catch (error) {
      if (error.name === 'AbortError') {
        console.info('Superseded example-list request aborted');
        return;
      }
      console.error(error);
      if (sequence === this.sequence) text('scenes-status', `Failed to load the created scenes: ${error.message}`);
    }
  }
}

export async function start(config) {
  const gallery = new Gallery(config);
  await gallery.load();
}
