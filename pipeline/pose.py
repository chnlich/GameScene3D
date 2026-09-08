import bpy,math
from mathutils import Vector,Matrix
def bone_matching(rig,*candidates):
 for candidate in candidates:
  found=[b for b in rig.pose.bones if b.name.lower().split(':')[-1].replace('_','').replace('.','')==candidate.lower().replace('_','').replace('.','')]
  if found:return found[0]
 raise KeyError((candidates,list(rig.pose.bones.keys())))

def rotate_local(bone,axis,angle):
 bone.rotation_mode='QUATERNION';bone.rotation_quaternion=bone.rotation_quaternion @ Matrix.Rotation(math.radians(angle),4,axis).to_quaternion();bpy.context.view_layer.update()

def aim_bone_at(rig,bone,target):
 # Changes articulated joint orientation, keeping the existing head anchor and roll.
 inv=rig.matrix_world.inverted();target=inv@Vector(target);bpy.context.view_layer.update();m=bone.matrix.copy();direction=(m.to_3x3()@Vector((0,1,0))).normalized();desired=(target-m.translation).normalized();q=direction.rotation_difference(desired);bone.matrix=Matrix.Translation(m.translation) @ q.to_matrix().to_4x4() @ m.to_3x3().to_4x4();bpy.context.view_layer.update()

def ik_target(rig,lower_bone,target,pole,name,c,chain=2,pole_angle=0):
 t=bpy.data.objects.new(name+' target',None);c.objects.link(t);t.location=target;t.empty_display_type='PLAIN_AXES';t.empty_display_size=.12
 p=bpy.data.objects.new(name+' pole',None);c.objects.link(p);p.location=pole;p.empty_display_type='SPHERE';p.empty_display_size=.08
 ik=lower_bone.constraints.new('IK');ik.name=name;ik.target=t;ik.pole_target=p;ik.chain_count=chain;ik.pole_angle=math.radians(pole_angle);ik.use_stretch=False
 bpy.context.view_layer.update();return t,p,ik
