"""Keep original mesh/UV/PBR. Transfer only skin weights from Meshy rig output."""
import bpy,os,json,math
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree

def bounds(meshes):
 points=[o.matrix_world@Vector(v) for o in meshes for v in o.bound_box]
 return Vector([min(v[i] for v in points) for i in range(3)]),Vector([max(v[i] for v in points) for i in range(3)])
def import_set(path):
 before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=os.path.abspath(path));return set(bpy.data.objects)-before

def create_character(original_path,rigged_path,label,collection):
 imported=import_set(rigged_path)
 rigs=[o for o in imported if o.type=='ARMATURE'];skins=[o for o in imported if o.type=='MESH' and any(m.type=='ARMATURE' for m in o.modifiers)]
 if len(rigs)!=1 or len(skins)!=1:raise RuntimeError('Weight transfer requires exactly one skeleton and one skinned source mesh')
 rig,skin=rigs[0],skins[0]
 for o in imported:
  if o not in [rig,skin]:bpy.data.objects.remove(o,do_unlink=True);continue
  if o.animation_data:o.animation_data_clear()
  for c in list(o.users_collection):c.objects.unlink(o)
  collection.objects.link(o);o.name=label+' • '+('weight source' if o==skin else 'rig')
 for b in rig.pose.bones:b.matrix_basis=Matrix.Identity(4)
 rig.data.pose_position='REST';bpy.context.view_layer.update()
 originals=import_set(original_path);meshes=[o for o in originals if o.type=='MESH']
 for o in originals:
  for c in list(o.users_collection):c.objects.unlink(o)
  collection.objects.link(o);o.name=label+' • original PBR '+o.name
 rlo,rhi=bounds([skin]);olo,ohi=bounds(meshes);scale=(rhi.z-rlo.z)/(ohi.z-olo.z);rc=(rlo+rhi)/2;oc=(olo+ohi)/2
 transform=Matrix.Translation(rc) @ Matrix.Scale(scale,4) @ Matrix.Translation(-oc)
 for o in originals:
  if o.parent not in originals:o.matrix_world=transform@o.matrix_world
 bpy.context.view_layer.update()
 # Compare the aligned source mesh to the rigged rest surface before admitting transfer.
 sv=[skin.matrix_world@v.co for v in skin.data.vertices];faces=[list(p.vertices) for p in skin.data.polygons];tree=BVHTree.FromPolygons(sv,faces,all_triangles=False)
 distances=[]
 for o in meshes:
  step=max(1,len(o.data.vertices)//1500)
  for vi in range(0,len(o.data.vertices),step):
   v=o.data.vertices[vi]
   hit=tree.find_nearest(o.matrix_world@v.co)
   if hit is None:raise RuntimeError('No nearest rig surface for source vertex')
   distances.append(hit[3])
 distances.sort();height=rhi.z-rlo.z;p50=distances[len(distances)//2];p95=distances[int(len(distances)*.95)];p99=distances[int(len(distances)*.99)]
 report={'original':os.path.basename(original_path),'rig_source':os.path.basename(rigged_path),'alignment_scale':scale,'aligned_original_bounds':[list(v) for v in bounds(meshes)],'rig_bounds':[list(rlo),list(rhi)],'surface_distance_median':p50,'surface_distance_p95':p95,'surface_distance_p99':p99,'p95_fraction_of_height':p95/height,'samples':len(distances),'uv_preserved':True,'material_names':[m.name for o in meshes for m in o.data.materials]}
 if p95/height>.035:raise RuntimeError('Rest meshes differ too much for nearest-surface weights: '+json.dumps(report))
 # Original material nodes and UVs stay unchanged. Only the vertex groups are copied.
 for o in meshes:
  for group in skin.vertex_groups:
   if not o.vertex_groups.get(group.name):o.vertex_groups.new(name=group.name)
  mod=o.modifiers.new('Transferred rest surface weights','DATA_TRANSFER');mod.object=skin;mod.use_vert_data=True;mod.data_types_verts={'VGROUP_WEIGHTS'};mod.vert_mapping='POLYINTERP_NEAREST';mod.layers_vgroup_select_src='ALL';mod.layers_vgroup_select_dst='NAME';mod.mix_mode='REPLACE';mod.mix_factor=1.0
  bpy.context.view_layer.objects.active=o;o.select_set(True);bpy.ops.object.modifier_apply(modifier=mod.name);o.select_set(False)
  world=o.matrix_world.copy();o.parent=rig;o.matrix_world=world;arm=o.modifiers.new('Articulated character skeleton','ARMATURE');arm.object=rig;arm.use_deform_preserve_volume=True
  report.setdefault('mesh_audit',[]).append({'name':o.name,'vertices':len(o.data.vertices),'faces':len(o.data.polygons),'uv_layers':len(o.data.uv_layers),'vertex_groups':len(o.vertex_groups),'unweighted_vertices':sum(not any(g.weight>.0001 for g in v.groups) for v in o.data.vertices)})
 # Bone tails arrive at approximately 100x their real joint distance. Fix lengths along existing axes.
 bpy.context.view_layer.objects.active=rig;rig.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
 for b in rig.data.edit_bones:
  if b.length>20:b.tail=b.head+(b.tail-b.head)*.01
 bpy.ops.object.mode_set(mode='OBJECT');rig.select_set(False);rig.data.pose_position='POSE'
 skin.hide_render=True;skin.hide_set(True);skin.display_type='WIRE';bpy.context.view_layer.update()
 return rig,meshes,report
