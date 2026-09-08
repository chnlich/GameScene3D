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
    text('job-status', '准备输入');
    text('job-message', '提交后显示服务器报告的实际步骤。切换输入会停止跟踪上一任务，服务器任务不会被取消。');
    text('scene-title', '三维场景');
    this.sceneNotice('可打开已完成场景旋转查看，或在制作工具中提交新输入。', false);
    text('camera-note', '拖动旋转 · 滚轮缩放 · 右键平移；触屏双指缩放与平移');
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
      text('input-status', '也可以只输入文字。');
      return;
    }
    text('input-status', '正在读取图片…');
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
      text('input-status', `已准备图片 · ${image.naturalWidth} × ${image.naturalHeight}`);
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
      this.requestError(error, context, '图片读取失败');
      if (this.current(context)) {
        $('image').value = '';
        text('input-status', '图片读取失败，请重新选择。');
      }
    }
  }

  requestError(error, context, label) {
    if (error.name === 'AbortError') {
      console.info('已停止旧请求', error.message);
      return;
    }
    console.error(error);
    if (!this.current(context)) return;
    $('page-error').hidden = false;
    text('page-error', `${label}：${error.message}`);
  }

  sceneNotice(message, failed) {
    $('scene-status').hidden = false;
    $('scene-status').classList.toggle('error', failed);
    text('scene-status', message);
  }

  sceneError(error) {
    console.error(error);
    this.sceneNotice(`三维场景加载失败：${error.message}`, true);
    $('reset-camera').disabled = true;
  }

  async health() {
    const sequence = ++this.healthSequence;
    text('health', '正在检查服务…');
    try {
      const health = await requestJSON('/api/health', {});
      if (sequence !== this.healthSequence) return;
      text('health', `${health.ok ? '服务在线' : '服务异常'} · ${health.generation_available ? '可生成' : '生成暂不可用'}。${health.generation_note}`);
    } catch (error) {
      console.error(error);
      if (sequence === this.healthSequence) text('health', `服务检查失败：${error.message}`);
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
    text('job-status', '正在提交');
    text('job-message', '等待服务器接受任务…');
    try {
      const job = await requestJSON('/api/jobs', { method: 'POST', body: form, signal: context.signal });
      await this.poll(job, context);
    } catch (error) {
      this.requestError(error, context, '生成提交失败');
      if (this.current(context)) {
        text('job-status', '提交未确认');
        text('job-message', '未收到任务确认。可检查服务或打开预生成示例。');
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
      this.requestError(error, context, '任务状态读取失败');
      if (this.current(context)) {
        text('job-message', '状态跟踪已中断，上方为最后一次服务器状态。可重新读取状态或打开预生成示例。');
        $('retry-status').hidden = false;
      }
    }
  }

  showJob(job, prerecorded) {
    switch (job.status) {
      case 'queued': text('job-status', '排队中'); break;
      case 'running': text('job-status', '生成中'); break;
      case 'succeeded': text('job-status', '服务器生成成功'); break;
      case 'failed': text('job-status', '生成失败'); break;
      default: throw new Error(`未知任务状态：${job.status}`);
    }
    text('job-origin', `${prerecorded ? '预生成示例' : '本次提交'} · ${job.id}`);
    text('job-message', `${job.progress.phase} · ${job.progress.message}`);
    $('progress').hidden = job.progress.fraction === null;
    if (job.progress.fraction !== null) {
      $('progress').value = job.progress.fraction;
      $('progress').setAttribute('aria-label', `服务器进度 ${Math.round(job.progress.fraction * 100)}%`);
    }
    if (job.status === 'failed') {
      $('job-error').hidden = false;
      text('job-error', `${job.error.code}：${job.error.message}。仍可打开下方预生成示例。`);
      this.sceneNotice('生成失败，没有可打开的新场景。', true);
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
    for (const [key, label] of [['glb', '下载 GLB'], ['blend', 'Blender 工程'], ['manifest', 'Manifest'], ['evidence', '生成证据']]) {
      if (result.artifacts[key]) {
        const link = document.createElement('a');
        link.href = safeURL(result.artifacts[key]);
        link.download = '';
        link.textContent = label;
        $('downloads').append(link);
      }
    }
    this.sceneNotice('正在加载三维场景与原图…', false);
    try {
      const original = result.artifacts.original === null ? null : await this.decodeImage(result.artifacts.original);
      if (!this.current(context)) return;
      this.showReference(original);
      const loaded = await this.viewer.load(safeURL(result.artifacts.glb), result.camera, original === null ? null : original.naturalWidth / original.naturalHeight);
      if (!loaded || !this.current(context)) return;
      $('scene-status').hidden = true;
      $('reset-camera').disabled = false;
      text('reset-camera', result.camera === null ? '恢复默认视角' : original === null ? '恢复生成视角' : '恢复原图相机');
      text('camera-note', `${result.camera === null ? '未提供原图相机，当前为默认视角。' : '已应用契约相机；保留 GLB 世界坐标。'} 拖动旋转 · 滚轮缩放 · 右键平移；触屏双指缩放与平移。`);
    } catch (error) {
      if (this.current(context)) {
        this.viewer.clear();
        this.sceneError(error);
        $('retry-scene').hidden = false;
      }
      else console.error('旧场景加载失败', error);
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
        text('job-origin', '输入素材 · 尚未生成');
        text('input-status', this.inputPending ? '正在读取示例图片…' : '文字已填入，点击生成。');
        if (example.input.image_url !== null) {
          const url = new URL(safeURL(example.input.image_url));
          if (url.origin !== location.origin || !url.pathname.startsWith('/demo/')) throw new Error('输入示例图片必须来自同源 /demo/');
          const response = await fetch(url, { signal: context.signal });
          if (!response.ok) throw new Error(`示例图片读取失败（HTTP ${response.status}）`);
          const blob = await response.blob();
          if (!this.current(context)) return;
          await this.setFile(new File([blob], url.pathname.split('/').at(-1), { type: blob.type }), context);
        }
      } else if (example.kind === 'scene') {
        $('prompt').value = example.job.input.prompt;
        this.updateSubmit();
        text('input-status', '正在查看预生成场景。可选择图片或输入文字再次提交。');
        if (example.job.status !== 'succeeded') throw new Error('场景示例未包含成功任务');
        this.showJob(example.job, true);
        await this.openResult(example.job, context);
      } else {
        throw new Error(`未知示例类型：${example.kind}`);
      }
    } catch (error) {
      this.requestError(error, context, '示例读取失败');
      if (this.current(context)) text('input-status', '示例未能准备完成，请重新选择。');
    } finally {
      if (this.current(context)) {
        this.inputPending = false;
        this.updateSubmit();
      }
    }
  }

  async loadExamples() {
    const sequence = ++this.examplesSequence;
    text('examples-status', '正在读取已完成场景…');
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
        if (example.kind === 'input') tag.textContent = '输入素材 · 尚未生成';
        else if (example.kind === 'scene') {
          if (example.job.status !== 'succeeded') throw new Error('场景示例未包含成功任务');
          tag.textContent = '已完成 · 预生成场景';
          scenes.push(example);
        }
        else throw new Error(`未知示例类型：${example.kind}`);
        const title = document.createElement('h3');
        title.textContent = example.title;
        const description = document.createElement('p');
        description.textContent = example.description;
        const provenance = document.createElement('dl');
        for (const [key, label] of [['source', '来源'], ['license', '许可'], ['attribution', '署名'], ['changes', '改动']]) {
          const term = document.createElement('dt');
          term.textContent = label;
          const value = document.createElement('dd');
          value.textContent = example[key];
          provenance.append(term, value);
        }
        if (example.license_url) {
          const link = document.createElement('a');
          link.href = safeURL(example.license_url);
          link.textContent = '许可条款';
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          const value = document.createElement('dd');
          value.append(link);
          provenance.append(value);
        }
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = example.kind === 'input' ? '使用此输入' : '打开预生成场景';
        button.addEventListener('click', () => this.selectExample(example));
        card.append(tag, title, description, provenance, button);
        if (example.kind === 'scene') sceneCards.push(card);
        else inputCards.push(card);
      }
      $('examples').replaceChildren(...sceneCards);
      $('input-examples').replaceChildren(...inputCards);
      text('examples-status', scenes.length === 0 ? '尚未发布完成场景。可展开制作工具准备输入。' : '已完成的预生成场景，打开即可旋转查看。来源、许可与修订说明见各场景。');
      text('inputs-status', inputCards.length === 0 ? '暂无候选输入素材。可上传图片或输入文字。' : '选择素材仅准备输入，提交后才会生成新场景。');
      if (!this.examplesLoaded) {
        this.examplesLoaded = true;
        // begin() advances before input decoding or scene loading can yield.
        if (this.sequence === 0) {
          if (scenes.length > 0) await this.selectExample(scenes[0]);
          else this.sceneNotice('尚未发布完成场景。可展开下方制作工具。', false);
        }
      }
    } catch (error) {
      console.error(error);
      if (sequence === this.examplesSequence) text('examples-status', `示例列表读取失败：${error.message}`);
    }
  }
}

export async function start(config) {
  const app = new App(config);
  await Promise.all([app.health(), app.loadExamples()]);
}
