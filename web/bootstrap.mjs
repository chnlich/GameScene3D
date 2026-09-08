try {
  const response = await fetch('/contracts/scene.schema.json');
  if (!response.ok) throw new Error(`契约读取失败（HTTP ${response.status}）`);
  const contract = await response.json();
  const config = contract['x-web'];
  const importMap = document.createElement('script');
  importMap.type = 'importmap';
  importMap.textContent = JSON.stringify({ imports: config.import_map });
  document.head.append(importMap);
  const { start } = await import('./app.mjs');
  await start(config);
} catch (error) {
  console.error(error);
  const notice = document.querySelector('#page-error');
  notice.hidden = false;
  notice.textContent = `页面初始化失败：${error.message}`;
}
