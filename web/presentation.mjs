export function metrics(result) {
  const elapsed = result.elapsed_seconds === null ? '耗时未知' : `耗时 ${result.elapsed_seconds.toFixed(1)} 秒`;
  const cost = result.cost_usd === null ? '费用未知' : `费用 $${result.cost_usd.toFixed(4)}`;
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
  if (!response.ok) throw new Error(`${body.code}：${body.message}（HTTP ${response.status}）`);
  return body;
}

export function safeURL(value) {
  const url = new URL(value, location.href);
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('资源链接必须是 HTTP 或 HTTPS');
  return url.href;
}
