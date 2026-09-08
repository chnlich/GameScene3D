import { Viewer } from './viewer.mjs';
import { metrics, requestJSON, safeURL } from './presentation.mjs';

const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };

class App {
  constructor(config) {
    this.sequence = 0;
    this.request = new AbortController();
    this.file = null;
    this.previewURL = null;
    this.inputPending = false;
    this.submitting = false;
    this.trackedJob = null;
    this.examplesSequence = 0;
    this.examplesLoaded = false;
    this.healthSequence = 0;
    this.viewer = new Viewer($('canvas-host'), config.draco_decoder_path, error => this.sceneError(error));
    $('generate-form').addEventListener('submit', event => {
      event.preventDefault();
      this.submit();
    });
    $('image').addEventListener('change', () => this.chooseFile($('image').files[0] ?? null));
    $('clear-image').addEventListener('click', () => {
      $('image').value = '';
      this.chooseFile(null);
    });
    $('prompt').addEventListener('input', () => {
      this.begin();
      this.inputPending = false;
      this.showInputPreview();
      this.updateSubmit();
    });
    $('reset-camera').addEventListener('click', () => this.viewer.reset());
    $('reload-examples').addEventListener('click', () => this.loadExamples());
    $('check-health').addEventListener('click', () => this.health());
    $('retry-status').addEventListener('click', () => {
      this.poll(this.trackedJob, { id: this.sequence, signal: this.request.signal });
    });
    $('retry-scene').addEventListener('click', () => {
      this.openResult(this.resultJob, { id: this.sequence, signal: this.request.signal });
    });
    window.addEventListener('pagehide', () => {
      this.request.abort();
      this.viewer.dispose();
      this.releasePreview();
    }, { once: true });
  }

  begin() {
    this.request.abort();
    this.request = new AbortController();
    this.sequence += 1;
    this.trackedJob = null;
    this.resultJob = null;
    this.submitting = false;
    $('retry-status').hidden = true;
    $('retry-scene').hidden = true;
    this.viewer.clear();
    $('reset-camera').disabled = true;
    $('downloads').replaceChildren();
    $('result-details').hidden = true;
    $('job-error').hidden = true;
    $('page-error').hidden = true;
    $('progress').hidden = true;
    text('metrics', '');
    text('job-origin', '');
    text('job-status', 'Preparing input');
    text('job-message', 'The steps reported by the server appear after submission. Changing input stops tracking the previous job; the server job is not cancelled.');
    text('scene-title', '3D scene');
    this.sceneNotice('Open a completed scene to rotate it, or submit new input in the production tools.', false);
    text('camera-note', 'Drag to rotate · Scroll to zoom · Right-drag to pan; touch: two fingers zoom and pan');
    return { id: this.sequence, signal: this.request.signal };
  }

  current(context) { return context.id === this.sequence; }

  updateSubmit() {
    $('prompt').disabled = this.inputPending;
    $('submit').disabled = this.submitting || this.inputPending || (!this.file && !$('prompt').value.trim());
    $('clear-image').disabled = !this.file && !this.inputPending;
  }

  releasePreview() {
    if (this.previewURL) URL.revokeObjectURL(this.previewURL);
    this.previewURL = null;
  }

  showReference(image) {
    $('reference-image').hidden = image === null;
    $('reference-empty').hidden = image !== null;
    if (image === null) {
      $('reference-image').removeAttribute('src');
      text('image-size', '');
    } else {
      $('reference-image').src = image.src;
      text('image-size', `${image.naturalWidth} × ${image.naturalHeight}`);
    }
  }

  showInputPreview() {
    this.showReference(this.inputImage ?? null);
  }

  async decodeImage(url) {
    const image = new Image();
    image.src = safeURL(url);
    await image.decode();
    return image;
  }

  async setFile(file, context) {
    this.releasePreview();
    this.file = null;
    this.inputImage = null;
    this.showReference(null);
    this.inputPending = file !== null;
    this.updateSubmit();
    if (file === null) {
      text('input-status', 'You can also enter text only.');
      return;
    }
    text('input-status', 'Reading the image…');
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
      if (!this.current(context)) {
        URL.revokeObjectURL(url);
        return;
      }
      this.previewURL = url;
      this.inputImage = image;
      this.file = file;
      this.showInputPreview();
      text('input-status', `Image ready · ${image.naturalWidth} × ${image.naturalHeight}`);
    } catch (error) {
      URL.revokeObjectURL(url);
      throw error;
    } finally {
      if (this.current(context)) {
        this.inputPending = false;
        this.updateSubmit();
      }
    }
  }

  async chooseFile(file) {
    const context = this.begin();
    try {
      await this.setFile(file, context);
    } catch (error) {
      this.requestError(error, context, 'Failed to read the image');
      if (this.current(context)) {
        $('image').value = '';
        text('input-status', 'The image could not be read; please choose again.');
      }
    }
  }

  requestError(error, context, label) {
    if (error.name === 'AbortError') {
      console.info('Superseded request aborted', error.message);
      return;
    }
    console.error(error);
    if (!this.current(context)) return;
    $('page-error').hidden = false;
    text('page-error', `${label}: ${error.message}`);
  }

  sceneNotice(message, failed) {
    $('scene-status').hidden = false;
    $('scene-status').classList.toggle('error', failed);
    text('scene-status', message);
  }

  sceneError(error) {
    console.error(error);
    this.sceneNotice(`Failed to load the 3D scene: ${error.message}`, true);
    $('reset-camera').disabled = true;
  }

  async health() {
    const sequence = ++this.healthSequence;
    text('health', 'Checking the service…');
    try {
      const health = await requestJSON('/api/health', {});
      if (sequence !== this.healthSequence) return;
      text('health', `${health.ok ? 'Service online' : 'Service error'} · ${health.generation_available ? 'generation available' : 'generation unavailable'}. ${health.generation_note}`);
    } catch (error) {
      console.error(error);
      if (sequence === this.healthSequence) text('health', `Service check failed: ${error.message}`);
    }
  }

  async submit() {
    const form = new FormData();
    form.set('prompt', $('prompt').value.trim());
    if (this.file) form.set('image', this.file);
    const context = this.begin();
    this.submitting = true;
    this.updateSubmit();
    this.showInputPreview();
    text('job-status', 'Submitting');
    text('job-message', 'Waiting for the server to accept the job…');
    try {
      const job = await requestJSON('/api/jobs', { method: 'POST', body: form, signal: context.signal });
      await this.poll(job, context);
    } catch (error) {
      this.requestError(error, context, 'Job submission failed');
      if (this.current(context)) {
        text('job-status', 'Submission not confirmed');
        text('job-message', 'No job confirmation was received. Check the service or open a prerecorded scene.');
      }
    } finally {
      if (this.current(context)) {
        this.submitting = false;
        this.updateSubmit();
      }
    }
  }

  async poll(job, context) {
    if (!this.current(context)) return;
    $('retry-status').hidden = true;
    $('page-error').hidden = true;
    try {
      while (this.current(context)) {
        this.trackedJob = job;
        this.showJob(job, false);
        if (job.status === 'succeeded') {
          await this.openResult(job, context);
          return;
        }
        if (job.status === 'failed') return;
        await new Promise(resolve => setTimeout(resolve, 1500));
        if (!this.current(context)) return;
        job = await requestJSON(`/api/jobs/${encodeURIComponent(job.id)}`, { signal: context.signal });
      }
    } catch (error) {
      this.requestError(error, context, 'Failed to read the job status');
      if (this.current(context)) {
        text('job-message', 'Status tracking was interrupted; the latest server status is shown above. Read the status again or open a prerecorded scene.');
        $('retry-status').hidden = false;
      }
    }
  }

  showJob(job, prerecorded) {
    switch (job.status) {
      case 'queued': text('job-status', 'Queued'); break;
      case 'running': text('job-status', 'Generating'); break;
      case 'succeeded': text('job-status', 'Generation succeeded on the server'); break;
      case 'failed': text('job-status', 'Generation failed'); break;
      default: throw new Error(`Unknown job status: ${job.status}`);
    }
    text('job-origin', `${prerecorded ? 'Prerecorded example' : 'This submission'} · ${job.id}`);
    text('job-message', `${job.progress.phase} · ${job.progress.message}`);
    $('progress').hidden = job.progress.fraction === null;
    if (job.progress.fraction !== null) {
      $('progress').value = job.progress.fraction;
      $('progress').setAttribute('aria-label', `Server progress ${Math.round(job.progress.fraction * 100)}%`);
    }
    if (job.status === 'failed') {
      $('job-error').hidden = false;
      text('job-error', `${job.error.code}: ${job.error.message}. The prerecorded scenes below remain available.`);
      this.sceneNotice('Generation failed; there is no new scene to open.', true);
    }
  }

  async openResult(job, context) {
    this.resultJob = job;
    $('retry-scene').hidden = true;
    const result = job.result;
    text('metrics', metrics(result));
    text('scene-title', result.title);
    text('summary', result.summary);
    $('assumptions').replaceChildren(...result.assumptions.map(assumption => {
      const item = document.createElement('li');
      item.textContent = assumption;
      return item;
    }));
    $('result-details').hidden = false;
    $('downloads').replaceChildren();
    for (const [key, label] of [['glb', 'Download GLB'], ['blend', 'Blender project'], ['manifest', 'Manifest'], ['evidence', 'Generation evidence']]) {
      if (result.artifacts[key]) {
        const link = document.createElement('a');
        link.href = safeURL(result.artifacts[key]);
        link.download = '';
        link.textContent = label;
        $('downloads').append(link);
      }
    }
    this.sceneNotice('Loading the 3D scene and the original image…', false);
    try {
      const original = result.artifacts.original === null ? null : await this.decodeImage(result.artifacts.original);
      if (!this.current(context)) return;
      this.showReference(original);
      const loaded = await this.viewer.load(safeURL(result.artifacts.glb), result.camera, original === null ? null : original.naturalWidth / original.naturalHeight);
      if (!loaded || !this.current(context)) return;
      $('scene-status').hidden = true;
      $('reset-camera').disabled = false;
      text('reset-camera', result.camera === null ? 'Reset default view' : original === null ? 'Reset generation view' : 'Reset source camera');
      text('camera-note', `${result.camera === null ? 'No source-image camera was provided; this is the default view.' : 'Contract camera applied; GLB world coordinates preserved.'} Drag to rotate · Scroll to zoom · Right-drag to pan; touch: two fingers zoom and pan.`);
    } catch (error) {
      if (this.current(context)) {
        this.viewer.clear();
        this.sceneError(error);
        $('retry-scene').hidden = false;
      }
      else console.error('Previous scene failed to load', error);
    }
  }

  async selectExample(example) {
    const context = this.begin();
    $('image').value = '';
    this.file = null;
    this.inputImage = null;
    this.releasePreview();
    this.showReference(null);
    this.inputPending = false;
    try {
      if (example.kind === 'input') {
        $('production-tools').open = true;
        $('prompt').value = example.input.prompt;
        this.inputPending = example.input.image_url !== null;
        this.updateSubmit();
        text('job-origin', 'Input example · not yet generated');
        text('input-status', this.inputPending ? 'Loading the example image…' : 'Prompt filled in; click Generate.');
        if (example.input.image_url !== null) {
          const url = new URL(safeURL(example.input.image_url));
          if (url.origin !== location.origin || !url.pathname.startsWith('/demo/')) throw new Error('Input example images must come from same-origin /demo/');
          const response = await fetch(url, { signal: context.signal });
          if (!response.ok) throw new Error(`Failed to load the example image (HTTP ${response.status})`);
          const blob = await response.blob();
          if (!this.current(context)) return;
          await this.setFile(new File([blob], url.pathname.split('/').at(-1), { type: blob.type }), context);
        }
      } else if (example.kind === 'scene') {
        $('prompt').value = example.job.input.prompt;
        this.updateSubmit();
        text('input-status', 'Viewing a prerecorded scene. Choose an image or enter a prompt to submit again.');
        if (example.job.status !== 'succeeded') throw new Error('Scene example does not contain a succeeded job');
        this.showJob(example.job, true);
        await this.openResult(example.job, context);
      } else {
        throw new Error(`Unknown example kind: ${example.kind}`);
      }
    } catch (error) {
      this.requestError(error, context, 'Failed to load the example');
      if (this.current(context)) text('input-status', 'The example could not be prepared; please choose again.');
    } finally {
      if (this.current(context)) {
        this.inputPending = false;
        this.updateSubmit();
      }
    }
  }

  async loadExamples() {
    const sequence = ++this.examplesSequence;
    text('examples-status', 'Loading completed scenes…');
    try {
      const examples = await requestJSON('/api/examples', {});
      if (sequence !== this.examplesSequence) return;
      const sceneCards = [];
      const inputCards = [];
      const scenes = [];
      for (const example of examples) {
        const card = document.createElement('article');
        card.className = 'example';
        const tag = document.createElement('span');
        tag.className = 'tag';
        if (example.kind === 'input') tag.textContent = 'Input example · not yet generated';
        else if (example.kind === 'scene') {
          if (example.job.status !== 'succeeded') throw new Error('Scene example does not contain a succeeded job');
          tag.textContent = 'Completed · prerecorded scene';
          scenes.push(example);
        }
        else throw new Error(`Unknown example kind: ${example.kind}`);
        const title = document.createElement('h3');
        title.textContent = example.title;
        const description = document.createElement('p');
        description.textContent = example.description;
        const provenance = document.createElement('dl');
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
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = example.kind === 'input' ? 'Use this input' : 'Open prerecorded scene';
        button.addEventListener('click', () => this.selectExample(example));
        card.append(tag, title, description, provenance, button);
        if (example.kind === 'scene') sceneCards.push(card);
        else inputCards.push(card);
      }
      $('examples').replaceChildren(...sceneCards);
      $('input-examples').replaceChildren(...inputCards);
      text('examples-status', scenes.length === 0 ? 'No completed scenes have been published yet. Expand the production tools to prepare an input.' : 'Completed prerecorded scenes; open one to rotate and explore. Source, license and revision notes are listed per scene.');
      text('inputs-status', inputCards.length === 0 ? 'No candidate input examples. Upload an image or enter a prompt.' : 'Selecting an example only prepares the input; a new scene is generated only after submission.');
      if (!this.examplesLoaded) {
        this.examplesLoaded = true;
        // begin() advances before input decoding or scene loading can yield.
        if (this.sequence === 0) {
          if (scenes.length > 0) await this.selectExample(scenes[0]);
          else this.sceneNotice('No completed scenes have been published yet. Expand the production tools below.', false);
        }
      }
    } catch (error) {
      console.error(error);
      if (sequence === this.examplesSequence) text('examples-status', `Failed to load the example list: ${error.message}`);
    }
  }
}

export async function start(config) {
  const app = new App(config);
  await Promise.all([app.health(), app.loadExamples()]);
}
