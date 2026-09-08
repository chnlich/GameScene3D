try {
  const response = await fetch('/contracts/scene.schema.json');
  if (!response.ok) throw new Error(`Failed to read the contract (HTTP ${response.status})`);
  const contract = await response.json();
  const config = contract['x-web'];
  const importMap = document.createElement('script');
  importMap.type = 'importmap';
  importMap.textContent = JSON.stringify({ imports: config.import_map });
  document.head.append(importMap);
  const page = document.body.dataset.page;
  const module = page === 'gallery' ? './gallery.mjs' : page === 'studio' ? './app.mjs' : null;
  if (module === null) throw new Error(`Unknown page: ${page ?? '(unset)'}`);
  const { start } = await import(module);
  await start(config);
} catch (error) {
  console.error(error);
  const notice = document.querySelector('#page-error');
  notice.hidden = false;
  notice.textContent = `The page failed to initialize: ${error.message}`;
}
