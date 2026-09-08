import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { containedSize } from './presentation.mjs';

export function disposeModel(root) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  const skeletons = new Set();
  root.traverse(object => {
    if (object.geometry) geometries.add(object.geometry);
    if (object.skeleton) skeletons.add(object.skeleton);
    if (object.material) {
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        materials.add(material);
        for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
      }
    }
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
  for (const skeleton of skeletons) skeleton.dispose();
  const bitmaps = new Set();
  for (const texture of textures) {
    if (texture.source.data instanceof ImageBitmap) bitmaps.add(texture.source.data);
    texture.dispose();
  }
  for (const bitmap of bitmaps) bitmap.close();
}

export class Viewer {
  constructor(host, decoderPath, reportError) {
    this.host = host;
    this.version = 0;
    this.model = null;
    this.controls = null;
    this.camera = null;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    host.append(this.renderer.domElement);
    this.renderer.domElement.addEventListener('webglcontextlost', event => {
      event.preventDefault();
      reportError(new Error('WebGL 上下文丢失，请刷新页面重新加载。'));
    });
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x090f12);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const room = new RoomEnvironment();
    this.environment = pmrem.fromScene(room, 0.04);
    this.scene.environment = this.environment.texture;
    room.dispose();
    pmrem.dispose();
    this.scene.add(new THREE.HemisphereLight(0xd9e7f4, 0x536452, 2));
    const light = new THREE.DirectionalLight(0xffffff, 3);
    light.position.set(4, 8, 6);
    this.scene.add(light);
    this.draco = new DRACOLoader();
    this.draco.setDecoderPath(decoderPath);
    this.draco.setWorkerLimit(1);
    this.loader = new GLTFLoader();
    this.loader.setDRACOLoader(this.draco);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(host);
  }

  clear() {
    this.version += 1;
    this.controls?.dispose();
    this.controls = null;
    this.camera = null;
    if (this.model) {
      this.scene.remove(this.model);
      disposeModel(this.model);
      this.model = null;
    }
    this.renderer.renderLists.dispose();
    this.renderer.clear();
  }

  async load(url, sourceCamera, imageAspect) {
    this.clear();
    const version = this.version;
    const gltf = await this.loader.loadAsync(url);
    if (version !== this.version) {
      disposeModel(gltf.scene);
      return false;
    }
    this.model = gltf.scene;
    this.scene.add(this.model);
    // The contract camera already uses final GLB coordinates. Keep the model's transforms intact.
    const sphere = new THREE.Box3().setFromObject(this.model).getBoundingSphere(new THREE.Sphere());
    if (sphere.radius <= 0 || !Number.isFinite(sphere.radius)) throw new Error('GLB 没有可显示的空间几何体');
    this.aspect = imageAspect ?? sourceCamera?.aspect_ratio ?? this.host.clientWidth / this.host.clientHeight;
    const distance = sourceCamera
      ? new THREE.Vector3().fromArray(sourceCamera.position).distanceTo(sphere.center)
      : sphere.radius * 3;
    const near = Math.max(sphere.radius * 0.00001, 0.000001);
    const far = Math.max(distance + sphere.radius * 100, near * 1000);
    if (sourceCamera === null || sourceCamera.projection === 'perspective') {
      this.camera = new THREE.PerspectiveCamera(sourceCamera === null ? 45 : sourceCamera.fov_degrees, this.aspect, near, far);
    } else if (sourceCamera.projection === 'orthographic') {
      const halfHeight = sourceCamera.orthographic_height / 2;
      this.camera = new THREE.OrthographicCamera(-halfHeight * this.aspect, halfHeight * this.aspect, halfHeight, -halfHeight, near, far);
    } else {
      throw new Error(`未知相机投影：${sourceCamera.projection}`);
    }
    const target = new THREE.Vector3();
    if (sourceCamera === null) {
      const halfVertical = THREE.MathUtils.degToRad(this.camera.fov / 2);
      const halfHorizontal = Math.atan(Math.tan(halfVertical) * this.aspect);
      const fitDistance = sphere.radius / Math.sin(Math.min(halfVertical, halfHorizontal)) * 1.1;
      this.camera.position.copy(sphere.center).add(new THREE.Vector3(1, 0.65, 1.5).normalize().multiplyScalar(fitDistance));
      target.copy(sphere.center);
    } else {
      this.camera.position.fromArray(sourceCamera.position);
      this.camera.up.fromArray(sourceCamera.up);
      target.fromArray(sourceCamera.target);
    }
    // OrbitControls derives its rotation frame from camera.up at construction.
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.copy(target);
    this.controls.addEventListener('change', () => this.render());
    this.controls.update();
    this.controls.saveState();
    this.resize();
    return true;
  }

  reset() {
    this.controls.reset();
    this.render();
  }

  resize() {
    if (!this.camera) return;
    const size = containedSize(this.host.clientWidth, this.host.clientHeight, this.aspect);
    this.renderer.setSize(size.width, size.height);
    this.render();
  }

  render() {
    if (this.camera) this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this.clear();
    this.resizeObserver.disconnect();
    this.draco.dispose();
    this.environment.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
