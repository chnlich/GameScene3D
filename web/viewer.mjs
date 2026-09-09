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
    this.renderer.toneMappingExposure = 0.85;
    host.append(this.renderer.domElement);
    this.renderer.domElement.addEventListener('webglcontextlost', event => {
      event.preventDefault();
      reportError(new Error('WebGL context lost; reload the page.'));
    });
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x090f12);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const room = new RoomEnvironment();
    this.environment = pmrem.fromScene(room, 0.04);
    this.scene.environment = this.environment.texture;
    this.scene.environmentIntensity = 0.35;
    room.dispose();
    pmrem.dispose();
    this.scene.add(new THREE.HemisphereLight(0xc8d9ed, 0x34423e, 0.6));
    for (const [color, intensity, x, y, z] of [
      [0xdde7ff, 2, -4, 8, 6],
      [0x96b6e0, 1.2, 4, 5, -4],
      [0xc5dfd3, 0.5, -5, 3, -3],
      [0xdce8ff, 0.9, 0, 4, 8],
    ]) {
      const light = new THREE.DirectionalLight(color, intensity);
      light.position.set(x, y, z);
      this.scene.add(light);
    }
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
    const bounds = new THREE.Box3().setFromObject(this.model, true);
    const sphere = bounds.getBoundingSphere(new THREE.Sphere());
    if (sphere.radius <= 0 || !Number.isFinite(sphere.radius)) throw new Error('GLB has no displayable spatial geometry');
    this.boundsSphere = sphere;
    this.aspect = imageAspect ?? sourceCamera?.aspect_ratio ?? this.host.clientWidth / this.host.clientHeight;
    // render() refits the clipping planes after every orbit, dolly, pan and reset.
    const near = sphere.radius / 250;
    const far = sphere.radius * 2;
    if (sourceCamera === null || sourceCamera.projection === 'perspective') {
      this.camera = new THREE.PerspectiveCamera(sourceCamera === null ? 38 : sourceCamera.fov_degrees, this.aspect, near, far);
    } else if (sourceCamera.projection === 'orthographic') {
      const halfHeight = sourceCamera.orthographic_height / 2;
      this.camera = new THREE.OrthographicCamera(-halfHeight * this.aspect, halfHeight * this.aspect, halfHeight, -halfHeight, near, far);
    } else {
      throw new Error(`Unknown camera projection: ${sourceCamera.projection}`);
    }
    const target = new THREE.Vector3();
    if (sourceCamera === null) {
      // Characters lead the frame: when skinned meshes exist they define the view and a
      // wide radius keeps the environment as background; otherwise textured or skinned
      // meshes stand in. Whole-scene bounds alone would frame floor planes.
      const skinned = new THREE.Box3();
      const textured = new THREE.Box3();
      this.model.traverse(object => {
        if (!object.isMesh) return;
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        if (object.isSkinnedMesh) skinned.expandByObject(object, true);
        if (object.isSkinnedMesh || materials.some(material => material.map)) textured.expandByObject(object, true);
      });
      const skinnedSphere = skinned.getBoundingSphere(new THREE.Sphere());
      const useCharacters = skinnedSphere.radius > 0 && Number.isFinite(skinnedSphere.radius);
      const frameBox = useCharacters ? skinned : textured;
      const frameMargin = useCharacters ? 2.35 : 1.15;
      let frameSphere = frameBox.getBoundingSphere(new THREE.Sphere());
      if (!(frameSphere.radius > 0) || !Number.isFinite(frameSphere.radius)) {
        frameBox.copy(bounds);
        frameSphere = sphere;
      }
      target.copy(frameBox.getCenter(new THREE.Vector3()));
      const halfVertical = THREE.MathUtils.degToRad(this.camera.fov / 2);
      const halfHorizontal = Math.atan(Math.tan(halfVertical) * this.aspect);
      // Portrait canvases have a narrower horizontal fov; fit the tighter of the two.
      const fitHalf = Math.min(halfVertical, halfHorizontal);
      const direction = new THREE.Vector3(4, 4, 14.5).normalize();
      const distance = (frameSphere.radius / Math.sin(fitHalf)) * frameMargin;
      this.camera.position.copy(target).addScaledVector(direction, distance);
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

  attach(host) {
    if (this.host !== host) {
      this.resizeObserver.disconnect();
      this.resizeObserver.observe(host);
      this.host = host;
    }
    host.append(this.renderer.domElement);
    this.resize();
  }

  detach() {
    this.resizeObserver.disconnect();
    this.renderer.domElement.remove();
  }

  resize() {
    if (!this.camera) return;
    const size = containedSize(this.host.clientWidth, this.host.clientHeight, this.aspect);
    this.renderer.setSize(size.width, size.height);
    this.render();
  }

  render() {
    if (!this.camera) return;
    const { center, radius } = this.boundsSphere;
    // Radius / 250 gives ~0.05 for a 12-unit scene; close inspection lowers it to 1% of target distance.
    this.camera.near = Math.min(radius / 250, this.camera.position.distanceTo(this.controls.target) / 100);
    // The whole scene sphere stays inside far at any orbit/pan/dolly distance, with 10% radius slack.
    this.camera.far = this.camera.position.distanceTo(center) + radius * 1.1;
    this.camera.updateProjectionMatrix();
    this.renderer.render(this.scene, this.camera);
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
