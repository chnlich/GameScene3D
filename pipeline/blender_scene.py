"""Blender-only data interpreter; model output is data, never executable code."""
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rig import bounds, create_character, import_set
from pose import bone_matching, ik_target


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2))


def material_check(objects):
    meshes = [o for o in objects if o.type == 'MESH']
    images = set()
    for o in meshes:
        if not o.data.materials or any(m is None for m in o.data.materials):
            raise RuntimeError('Generated mesh has missing materials')
        for material in o.data.materials:
            if material.use_nodes:
                for node in material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE':
                        if node.image is None:
                            raise RuntimeError('Material texture is missing: ' + material.name)
                        # Packed glTF images decode lazily; accessing pixels tests actual readability.
                        pixels = node.image.pixels[:4]
                        if len(pixels) != 4 or min(node.image.size) <= 0 or not all(math.isfinite(v) for v in pixels):
                            raise RuntimeError('Material texture is not readable: ' + node.image.name)
                        if node.image.packed_file:
                            images.add(hashlib.sha256(node.image.packed_file.data).hexdigest())
                        else:
                            images.add(hashlib.sha256(bytes(str(list(node.image.pixels[:64])), 'utf8')).hexdigest())
    if not meshes or not sum(len(o.data.polygons) for o in meshes):
        raise RuntimeError('Asset has no actual mesh faces')
    return {'meshes': len(meshes), 'faces': sum(len(o.data.polygons) for o in meshes),
            'materials': len({m for o in meshes for m in o.data.materials}),
            'texture_hashes': sorted(images), 'uv_meshes': sum(bool(o.data.uv_layers) for o in meshes)}


def character(original, rigged, identity, collection):
    source_objects = import_set(original)
    source_quality = material_check(source_objects)
    for o in source_objects:
        bpy.data.objects.remove(o, do_unlink=True)
    rig_objects = import_set(rigged)
    try:
        rig_quality = material_check(rig_objects)
    except RuntimeError as error:
        rig_quality = {'failure': str(error), 'texture_hashes': [],
                       'uv_meshes': 0, 'meshes': len([o for o in rig_objects if o.type == 'MESH'])}
        print(json.dumps({'rig_material_failure': rig_quality, 'action': 'preserve original materials'}), flush=True)
    # Exact embedded texture identity plus UV presence admits a direct rig.
    # Differing textures require preserving original UV/PBR with the 3.5% surface check.
    direct = (bool(source_quality['texture_hashes']) and
              source_quality['texture_hashes'] == rig_quality['texture_hashes'] and
              rig_quality['uv_meshes'] == rig_quality['meshes'])
    if direct:
        rigs = [o for o in rig_objects if o.type == 'ARMATURE']
        if len(rigs) != 1:
            raise RuntimeError('Expected one generated skeleton')
        rig = rigs[0]
        meshes = [o for o in rig_objects if o.type == 'MESH']
        for o in rig_objects:
            if o.animation_data:
                o.animation_data_clear()
        for bone in rig.pose.bones:
            bone.matrix_basis = Matrix.Identity(4)
        rig.data.pose_position = 'POSE'
        report = {'method': 'direct', 'source_quality': source_quality, 'rig_quality': rig_quality}
    else:
        for o in rig_objects:
            bpy.data.objects.remove(o, do_unlink=True)
        rig, meshes, report = create_character(original, rigged, identity, collection)
        report.update(method='UV-preserving weight transfer', source_quality=source_quality, rig_quality=rig_quality)
    for o in meshes:
        if any(not any(g.weight > .0001 for g in v.groups) for v in o.data.vertices):
            raise RuntimeError('Required articulated mesh contains unweighted vertices')
    return rig, meshes, report


def transform_matrix(data):
    return (Matrix.Translation(Vector(data['position'])) @
            Euler(tuple(math.radians(a) for a in data['rotation_degrees']), 'XYZ').to_matrix().to_4x4() @
            Matrix.Diagonal(Vector((*data['scale'], 1))))


def normalize(objects, meshes, asset):
    lo, hi = bounds(meshes)
    height = hi.z - lo.z
    if height <= 0:
        raise RuntimeError('Generated asset has zero height')
    bottom = Vector(((lo.x+hi.x)/2, (lo.y+hi.y)/2, lo.z))
    # Meshy front is glTF +Z, imported as Blender -Y; internal assets face +Y.
    matrix = (transform_matrix(asset['transform']) @ Matrix.Rotation(math.pi, 4, 'Z') @
              Matrix.Scale(asset['height_meters']/height, 4) @ Matrix.Translation(-bottom))
    for o in objects:
        if o.parent not in objects:
            o.matrix_world = matrix @ o.matrix_world
    bpy.context.view_layer.update()


def camera(scene, data, height):
    bpy.ops.object.camera_add(location=data['position'])
    obj = bpy.context.object
    obj.name = 'source_camera'
    forward = (Vector(data['target']) - Vector(data['position'])).normalized()
    right = forward.cross(Vector(data['up'])).normalized()
    up = right.cross(forward).normalized()
    obj.rotation_euler = Matrix((right, up, -forward)).transposed().to_euler()
    obj.data.clip_start = .01
    obj.data.clip_end = 10000
    scene.camera = obj
    scene.render.resolution_x = round(height * data['aspect_ratio'])
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1
    scene.render.pixel_aspect_y = 1
    # Vertical sensor fit keeps fov_degrees and orthographic_height vertical.
    obj.data.sensor_fit = 'VERTICAL'
    if data['projection'] == 'perspective':
        obj.data.type = 'PERSP'
        obj.data.sensor_height = 32
        obj.data.lens = 16 / math.tan(math.radians(data['fov_degrees']) / 2)
    else:
        obj.data.type = 'ORTHO'
        obj.data.ortho_scale = data['orthographic_height']
    return obj


def primitive(data):
    shape = data['shape']
    if shape == 'box':
        bpy.ops.mesh.primitive_cube_add(size=1)
    elif shape == 'sphere':
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=.5)
    elif shape == 'cylinder':
        bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=.5, depth=1)
    elif shape == 'cone':
        bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=.5, radius2=0, depth=1)
    else:
        raise ValueError('Unsupported primitive')
    obj = bpy.context.object
    obj.name = data['id']
    obj.matrix_world = transform_matrix(data['transform'])
    material = bpy.data.materials.new(data['id'] + '_material')
    material.use_nodes = True
    shader = material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = data['color']
    shader.inputs['Metallic'].default_value = data['metallic']
    shader.inputs['Roughness'].default_value = data['roughness']
    shader.inputs['Emission Color'].default_value = data['color']
    shader.inputs['Emission Strength'].default_value = data['emission']
    obj.data.materials.append(material)
    return obj


def evaluated_bounds(objects):
    graph = bpy.context.evaluated_depsgraph_get()
    points = []
    for obj in objects:
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        points.extend(evaluated.matrix_world @ v.co for v in mesh.vertices)
        evaluated.to_mesh_clear()
    return [min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]


def lighting(scene, data):
    for item in data['lights']:
        lamp = bpy.data.lights.new('scene_light', item['kind'])
        lamp.energy = item['energy']
        lamp.color = item['color']
        if item['kind'] == 'AREA':
            lamp.shape = 'DISK'
            lamp.size = item['size']
        elif item['kind'] == 'POINT':
            lamp.shadow_soft_size = item['size']
        else:
            lamp.angle = item['size']
        obj = bpy.data.objects.new('scene_light', lamp)
        scene.collection.objects.link(obj)
        obj.location = item['position']
        obj.rotation_euler = (Vector(item['target'])-obj.location).to_track_quat('-Z', 'Y').to_euler()
    scene.world = bpy.data.worlds.new('scene_world')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (*data['world_color'], 1)


def render(scene, settings, path):
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = settings['samples']
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def compose(job, root, destination):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    data, assets, settings = job['scene'], job['assets'], job['blender']
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    groups, reports, pose_checks = {}, {}, []
    for asset in data['assets']:
        paths = assets[asset['id']]
        before = set(bpy.data.objects)
        if asset['articulated']:
            if not paths.get('rig'):
                raise RuntimeError('Articulated asset has no rig; enable rigging or use static reconstruction')
            collection = bpy.data.collections.new(asset['id'])
            scene.collection.children.link(collection)
            rig, meshes, report = character(str(root / paths['model']), str(root / paths['rig']), asset['id'], collection)
            reports[asset['id']] = report
        else:
            imported = import_set(str(root / paths['model']))
            meshes = [o for o in imported if o.type == 'MESH']
            reports[asset['id']] = material_check(imported)
        objects = set(bpy.data.objects) - before
        normalize(objects, meshes, asset)
        groups[asset['id']] = meshes
        for index, o in enumerate(meshes):
            o.name = asset['id'] + '_' + str(index)
        for goal in asset['pose']:
            bone = bone_matching(rig, goal['bone'])
            ik_target(rig, bone, goal['target'], goal['pole'], asset['id'] + '_' + goal['bone'], collection,
                      goal['chain_length'], goal['pole_angle_degrees'])
            bpy.context.view_layer.update()
            achieved = rig.matrix_world @ bone.tail
            pose_checks.append({'asset': asset['id'], 'bone': bone.name, 'target': goal['target'],
                                'achieved': list(achieved), 'error_meters': (achieved-Vector(goal['target'])).length})
    for item in data['primitives']:
        groups[item['id']] = [primitive(item)]
    lighting(scene, data)
    cam = camera(scene, data['camera'], settings['resolution_height'])
    bpy.context.view_layer.update()
    geometry = {identity: evaluated_bounds(meshes) for identity, meshes in groups.items()}
    landmarks = []
    for landmark in data['landmarks']:
        lo, hi = geometry[landmark['asset_id']]
        point = [(a+b)/2 for a, b in zip(lo, hi)]
        if landmark['point'] == 'bottom':
            point[2] = lo[2]
        elif landmark['point'] == 'top':
            point[2] = hi[2]
        projected = world_to_camera_view(scene, cam, Vector(point))
        xy = [projected.x, 1-projected.y]
        error = math.dist(xy, landmark['image_xy'])
        landmarks.append(dict(landmark, projected_xy=xy, depth=projected.z, error=error))
    checks = {'geometry_bounds': geometry, 'materials': reports, 'pose': pose_checks, 'reprojection': landmarks,
              'pose_applicable': bool(pose_checks),
              'pose_passed': all(p['error_meters'] <= settings['pose_tolerance_meters'] for p in pose_checks),
              'reprojection_passed': bool(landmarks) and all(p['depth'] > 0 and p['error'] <= settings['reprojection_tolerance'] for p in landmarks)}
    dump(destination / 'checks.json', checks)
    render(scene, settings, destination / 'preview.png')
    bpy.ops.file.pack_all()
    for image in bpy.data.images:
        if image.packed_file:
            image.filepath = '//' + image.name
    # Render location and packed image names in downloadable .blend are relative.
    scene.render.filepath = '//preview.png'
    bpy.ops.wm.save_as_mainfile(filepath=str(destination / 'scene.blend'))
    graph = bpy.context.evaluated_depsgraph_get()
    baked = []
    for obj in list(scene.objects):
        if obj.type != 'MESH' or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=graph)
        copy = bpy.data.objects.new(obj.name + '_evaluated', mesh)
        copy.matrix_world = evaluated.matrix_world.copy()
        scene.collection.objects.link(copy)
        baked.append(copy)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in baked:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = baked[0]
    bpy.ops.export_scene.gltf(filepath=str(destination / 'scene.glb'), export_format='GLB',
                              use_selection=True, export_yup=True, export_animations=False,
                              export_skins=False, export_cameras=False, export_lights=False,
                              export_image_format='AUTO')


def verify(job, root, destination):
    reports = {}
    for extension in ('blend', 'glb'):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        path = root / ('scene.' + extension)
        if extension == 'blend':
            bpy.ops.wm.open_mainfile(filepath=str(path))
        else:
            bpy.ops.import_scene.gltf(filepath=str(path))
        meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and not o.hide_render]
        report = material_check(meshes)
        report['bounds'] = evaluated_bounds(meshes)
        reports[extension] = report
        if extension == 'glb':
            scene = bpy.context.scene
            lighting(scene, job['scene'])
            camera(scene, job['scene']['camera'], job['blender']['resolution_height'])
            render(scene, job['blender'], destination / 'reopen.png')
    if reports['blend']['faces'] > reports['glb']['faces']:
        raise RuntimeError('Export lost mesh faces')
    for first, second in zip(reports['blend']['bounds'], reports['glb']['bounds']):
        if math.dist(first, second) > .01:
            raise RuntimeError('GLB import changed composed world bounds')
    dump(destination / 'reopen.json', reports)


if __name__ == '__main__':
    mode, job_file, root, destination = sys.argv[sys.argv.index('--')+1:]
    job = json.loads(Path(job_file).read_text())
    if mode == 'compose':
        compose(job, Path(root), Path(destination))
    elif mode == 'verify':
        verify(job, Path(root), Path(destination))
    else:
        raise ValueError('Unknown Blender operation')
