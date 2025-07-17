
bl_info = {
    "name": "Remote Render Client",
    "author": "Wys",
    "version": (1, 1),
    "blender": (4, 0, 0),
    "location": "3D View > Sidebar > Remote Render",
    "description": "Send render jobs to remote server",
    "category": "Render",
}

import bpy
from bpy.props import StringProperty, EnumProperty, PointerProperty
from bpy.types import Panel, Operator, PropertyGroup
import os

try:
    from . import client
except ImportError:
    import client

class RemoteRenderProperties(PropertyGroup):
    filepath: StringProperty(
        name="Blend File",
        description="Path to .blend file to send",
        subtype='FILE_PATH',
    )
    render_type: EnumProperty(
        name="Render Type",
        description="Type of render",
        items=[
            ('image', "Image", "Render a single image"),
            ('animation', "Animation", "Render full animation"),
        ],
        default='image',
    )
    output_format: EnumProperty(
        name="Output Format",
        description="Format of rendered output",
        items=[
            ('PNG', "PNG", ""),
            ('FFMPEG', "FFMPEG", ""),
            ('JPEG', "JPEG", ""),
        ],
        default='PNG',
    )

class RENDERCLIENT_OT_send_job(Operator):
    bl_idname = "renderclient.send_job"
    bl_label = "Send Render Job"
    bl_description = "Send the current .blend or chosen file to remote render server"

    def execute(self, context):
        props = context.scene.remote_render_props
        path = props.filepath
        if not path:
            self.report({'ERROR'}, "Please select a .blend file")
            return {'CANCELLED'}
        if not os.path.isfile(path):
            self.report({'ERROR'}, "File does not exist")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Sending {os.path.basename(path)} for remote rendering...")
        job_id = client.send_render_job(
            blend_path=path,
            render_type=props.render_type,
            output_format=props.output_format,
            config=None,
            log=lambda msg: self.report({'INFO'}, msg)
        )
        if job_id:
            self.report({'INFO'}, f"Render job sent successfully! Job ID: {job_id}")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Failed to send render job")
            return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class RENDERCLIENT_PT_panel(Panel):
    bl_label = "Remote Render Client"
    bl_idname = "RENDERCLIENT_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Remote Render'

    def draw(self, context):
        layout = self.layout
        props = context.scene.remote_render_props

        layout.prop(props, "filepath")
        layout.prop(props, "render_type")
        layout.prop(props, "output_format")
        layout.operator(RENDERCLIENT_OT_send_job.bl_idname, text="Send Render Job")

def register():
    bpy.utils.register_class(RemoteRenderProperties)
    bpy.types.Scene.remote_render_props = PointerProperty(type=RemoteRenderProperties)
    bpy.utils.register_class(RENDERCLIENT_OT_send_job)
    bpy.utils.register_class(RENDERCLIENT_PT_panel)

def unregister():
    bpy.utils.unregister_class(RENDERCLIENT_PT_panel)
    bpy.utils.unregister_class(RENDERCLIENT_OT_send_job)
    del bpy.types.Scene.remote_render_props
    bpy.utils.unregister_class(RemoteRenderProperties)

if __name__ == "__main__":
    register()
