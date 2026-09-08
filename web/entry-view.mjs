import { metrics, safeURL } from './presentation.mjs';

export function mediaFigure(caption) {
  const figure = document.createElement('figure');
  figure.className = 'media';
  const label = document.createElement('figcaption');
  label.textContent = caption;
  const body = document.createElement('div');
  body.className = 'media-body';
  figure.append(label, body);
  return { figure, label, body };
}

export function originalPane(example, result) {
  const textOnly = example.job.input.image_url === null;
  const pane = mediaFigure(textOnly ? 'Text prompt · previous export' : 'Original input');
  let originalImg = null;
  if (result.artifacts.original) {
    originalImg = new Image();
    originalImg.alt = textOnly
      ? `Previous export before self-correction for ${example.title}`
      : `Original input image for ${example.title}`;
    originalImg.src = safeURL(result.artifacts.original);
    originalImg.className = 'fill';
    originalImg.loading = 'lazy';
    if (textOnly) {
      const promptCard = document.createElement('p');
      promptCard.className = 'media-empty';
      promptCard.textContent = example.job.input.prompt;
      pane.body.style.flexDirection = 'column';
      pane.body.append(promptCard);
      originalImg.style.flex = '1';
      originalImg.style.minHeight = '0';
      originalImg.style.height = 'auto';
    }
    pane.body.append(originalImg);
  } else {
    const empty = document.createElement('p');
    empty.className = 'media-empty';
    empty.textContent = 'No original image; this scene was created from a text prompt.';
    pane.body.append(empty);
  }
  return { figure: pane.figure, originalImg };
}

export function provenanceList(example) {
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
  return provenance;
}

export function assumptionsBlock(result) {
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
  return assumptionsWrap;
}

export function entryFoot(result) {
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
  return foot;
}
