import { requestJSON, safeURL } from './presentation.mjs';
import { mediaFigure, originalPane, provenanceList, assumptionsBlock, entryFoot } from './entry-view.mjs';

const $ = id => document.getElementById(id);
const text = (id, value) => { $(id).textContent = value; };

class Gallery {
  constructor(config) {
    this.config = config;
    this.sequence = 0;
    this.request = new AbortController();
    $('reload-scenes').addEventListener('click', () => this.load());
    window.addEventListener('pagehide', () => {
      this.request.abort();
    }, { once: true });
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
    const openLink = document.createElement('a');
    openLink.className = 'primary pointer-link';
    openLink.href = `/web/scene.html?id=${encodeURIComponent(example.id)}`;
    openLink.textContent = 'Load 3D view';
    actions.append(openLink);
    head.append(heading, actions);

    const media = document.createElement('div');
    media.className = 'entry-media';
    const textOnly = example.job.input.image_url === null;
    const original = originalPane(example, result);
    const sidePane = mediaFigure(textOnly ? 'Final render · after self-correction' : 'Preview');
    if (result.artifacts.preview) {
      const previewImg = new Image();
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
    media.append(original.figure, sidePane.figure);

    const provenance = provenanceList(example);
    const assumptions = assumptionsBlock(result);
    const foot = entryFoot(result);
    entry.append(head, media, provenance, assumptions, foot);
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
      $('scenes').replaceChildren(...scenes.map(example => this.buildEntry(example)));
      text('scenes-status', scenes.length === 0
        ? 'No created scenes have been published yet. The Interactive Studio can generate new ones.'
        : 'Open “Load 3D view” on an entry to explore the scene on its own page.');
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
