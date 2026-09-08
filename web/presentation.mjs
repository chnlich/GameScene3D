export const CONTROLS_NOTE = ' Drag to rotate · scroll to zoom · right-drag to pan; touch: one finger rotates, two fingers zoom and pan.';

export function cameraNote(camera) {
  return camera === null
    ? 'Default view — no verified source-image camera exists for this prerecorded scene.'
    : 'Source-image camera applied in the GLB world coordinates.';
}

export function metrics(result) {
  const elapsed = result.elapsed_seconds === null ? 'Time unknown' : `${result.elapsed_seconds.toFixed(1)} s elapsed`;
  const cost = result.cost_usd === null ? 'Cost unknown' : `Cost $${result.cost_usd.toFixed(4)}`;
  return `${elapsed} · ${cost} · ${result.cost_note}`;
}

export function containedSize(width, height, aspect) {
  return width / height > aspect
    ? { width: height * aspect, height }
    : { width, height: width / aspect };
}

export async function requestJSON(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(`${body.code}: ${body.message} (HTTP ${response.status})`);
  return body;
}

export function safeURL(value) {
  const url = new URL(value, location.href);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('Resource URLs must be HTTP or HTTPS');
  return url.href;
}
