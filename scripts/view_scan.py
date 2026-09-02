"""Rend le maillage photogrammetrique Apple Flyover (texture) depuis un point
de vue donne, pour verifier un detail bati contre la source."""
import bpy, math, sys
from mathutils import Vector
av = sys.argv[sys.argv.index("--")+1:]
OBJ, OUT = av[0], av[1]
TX, TY, TZ = float(av[2]), float(av[3]), float(av[4])
AZ, EL, DIST = float(av[5]), float(av[6]), float(av[7])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.obj(filepath=OBJ, axis_forward='Y', axis_up='Z')
tgt = Vector((TX, TY, TZ))
cd = bpy.data.cameras.new("C"); cd.lens = 55
cam = bpy.data.objects.new("C", cd); bpy.context.scene.collection.objects.link(cam)
a, e = math.radians(AZ), math.radians(EL)
cam.location = tgt + Vector((DIST*math.cos(e)*math.cos(a), DIST*math.cos(e)*math.sin(a), DIST*math.sin(e)))
cam.rotation_euler = (tgt-cam.location).to_track_quat('-Z','Y').to_euler()
bpy.context.scene.camera = cam
w = bpy.data.worlds.new("W"); w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (1,1,1,1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.9
bpy.context.scene.world = w
s = bpy.context.scene
s.render.engine='CYCLES'; s.cycles.device='CPU'; s.cycles.samples=24
s.render.resolution_x=1500; s.render.resolution_y=1000
s.render.filepath=OUT; s.render.image_settings.file_format='PNG'
bpy.ops.render.render(write_still=True); print("RENDERED")
