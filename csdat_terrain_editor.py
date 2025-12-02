import bpy
import os
import glob
import numpy as np
from bpy_extras.io_utils import ImportHelper
import io

bl_info = {
    "name": "CSDAT Terrain Editor",
    "author": "Your Name",
    "version": (1, 0, 1),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Terrain Editor",
    "description": "Import and export terrain heightmaps from CSDAT files",
    "category": "Import-Export",
}

# Global storage for sector data and settings
class TerrainEditorData:
    def __init__(self):
        self.sectors_data = {}
        self.current_directory = ""
        self.grid_size = 65
        self.sectors_x = 8
        self.sectors_y = 8
        self.terrain_object = None
        self.heightmap_image = None
        
terrain_data = TerrainEditorData()

def load_single_sector(file_path, grid_size=65):
    """Load height map data from a single .csdat file"""
    try:
        height_map = {}
        
        with open(file_path, 'rb') as f:
            f.seek(708)
            terrain_data_bytes = io.BytesIO(f.read(16900))
        
        for y in range(grid_size):
            row = []
            for x in range(grid_size):
                data = terrain_data_bytes.read(2)
                if len(data) < 2:
                    break
                height = int.from_bytes(data, 'little') / 128
                row.append(height)
                terrain_data_bytes.read(2)  # skip unknown data
            height_map[y] = row
        
        # Convert to numpy array
        height_array = np.array([height_map[y] for y in range(grid_size)])
        return height_array
        
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return None

def load_sectors_from_directory(directory, sectors_x, sectors_y):
    """Load all .csdat files from directory"""
    sectors_data = {}
    pattern = os.path.join(directory, "sd*.csdat")
    files = glob.glob(pattern)
    
    for file_path in files:
        filename = os.path.basename(file_path)
        try:
            sector_num = int(filename[2:-6])  # Extract sector number
            height_data = load_single_sector(file_path)
            if height_data is not None:
                sectors_data[sector_num] = height_data
        except ValueError:
            continue
    
    return sectors_data

def create_combined_heightmap(sectors_data, sectors_x, sectors_y, grid_size=65):
    """Create a combined heightmap from all sectors"""
    total_width = sectors_x * grid_size
    total_height = sectors_y * grid_size
    
    combined_map = np.zeros((total_height, total_width))
    
    for display_row in range(sectors_y):
        for col in range(sectors_x):
            # Convert display row to sector row (flip Y axis)
            sector_row = sectors_y - 1 - display_row
            sector_index = sector_row * sectors_x + col
            
            if sector_index in sectors_data:
                start_y = display_row * grid_size
                end_y = start_y + grid_size
                start_x = col * grid_size
                end_x = start_x + grid_size
                
                # Flip sector vertically
                flipped_sector = np.flipud(sectors_data[sector_index])
                combined_map[start_y:end_y, start_x:end_x] = flipped_sector
    
    # Rotate 90 degrees counter-clockwise, then flip horizontally
    combined_map = np.rot90(combined_map, k=1)
    combined_map = np.fliplr(combined_map)
    
    return combined_map

def numpy_to_blender_image(numpy_array, name="TerrainHeightmap", rotate_texture=False):
    """Convert numpy array to Blender image"""
    # Rotate texture an additional 90 degrees counter-clockwise for display
    if rotate_texture:
        numpy_array = np.rot90(numpy_array, k=1)
    
    height, width = numpy_array.shape
    
    # Normalize to 0-1 range
    min_val = np.min(numpy_array)
    max_val = np.max(numpy_array)
    if max_val > min_val:
        normalized = (numpy_array - min_val) / (max_val - min_val)
    else:
        normalized = np.zeros_like(numpy_array)
    
    # Create RGBA image (Blender needs 4 channels)
    rgba_array = np.zeros((height, width, 4), dtype=np.float32)
    rgba_array[:, :, 0] = normalized  # R
    rgba_array[:, :, 1] = normalized  # G
    rgba_array[:, :, 2] = normalized  # B
    rgba_array[:, :, 3] = 1.0  # A (fully opaque)
    
    # Flatten for Blender
    pixels = rgba_array.flatten()
    
    # Create or update image in Blender
    if name in bpy.data.images:
        img = bpy.data.images[name]
        img.scale(width, height)
    else:
        img = bpy.data.images.new(name, width, height, alpha=True)
    
    img.pixels = pixels
    img.update()
    img.pack()
    
    return img

def blender_image_to_numpy(image):
    """Convert Blender image to numpy array (grayscale)"""
    width = image.size[0]
    height = image.size[1]
    
    # Get pixels as numpy array
    pixels = np.array(image.pixels[:])
    
    # Reshape to (height, width, 4)
    pixels = pixels.reshape((height, width, 4))
    
    # Extract grayscale (use R channel)
    grayscale = pixels[:, :, 0]
    
    return grayscale

def write_sector_to_file(file_path, height_data, grid_size=65):
    """Write height data back to a .csdat file"""
    try:
        # Read the entire file first
        with open(file_path, 'rb') as f:
            file_content = bytearray(f.read())
        
        # Prepare to write terrain data starting at byte 708
        terrain_offset = 708
        
        # Flip the height data vertically back (undo the flip from loading)
        height_data_flipped = np.flipud(height_data)
        
        for y in range(grid_size):
            for x in range(grid_size):
                # Convert height back to original scale
                height_value = int(height_data_flipped[y, x] * 128)
                # Clamp to valid range
                height_value = max(0, min(65535, height_value))
                
                # Calculate position in file
                pos = terrain_offset + (y * grid_size + x) * 4
                
                # Write height as little-endian 2-byte integer
                file_content[pos:pos+2] = height_value.to_bytes(2, 'little')
                # Skip the next 2 bytes (unknown data/flags)
        
        # Write back to file
        with open(file_path, 'wb') as f:
            f.write(file_content)
        
        return True
        
    except Exception as e:
        print(f"Error writing to {file_path}: {e}")
        return False

# Operator: Import terrain
class TERRAIN_OT_import(bpy.types.Operator, ImportHelper):
    bl_idname = "terrain.import_csdat"
    bl_label = "Import CSDAT Terrain"
    bl_description = "Import terrain from CSDAT files"
    bl_options = {'REGISTER', 'UNDO'}
    
    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    
    sectors_x: bpy.props.IntProperty(
        name="Sectors X",
        description="Number of sectors in X direction",
        default=8,
        min=1,
        max=100
    )
    
    sectors_y: bpy.props.IntProperty(
        name="Sectors Y", 
        description="Number of sectors in Y direction",
        default=8,
        min=1,
        max=100
    )
    
    height_scale: bpy.props.IntProperty(
        name="Height Scale",
        description="Multiplier for terrain height displacement",
        default=1,
        min=1,
        max=100
    )
    
    def execute(self, context):
        global terrain_data
        
        # Store settings
        terrain_data.current_directory = self.directory
        terrain_data.sectors_x = self.sectors_x
        terrain_data.sectors_y = self.sectors_y
        
        # Load sectors
        self.report({'INFO'}, f"Loading sectors from {self.directory}")
        terrain_data.sectors_data = load_sectors_from_directory(
            self.directory, 
            self.sectors_x, 
            self.sectors_y
        )
        
        if not terrain_data.sectors_data:
            self.report({'ERROR'}, "No valid .csdat files found")
            return {'CANCELLED'}
        
        self.report({'INFO'}, f"Loaded {len(terrain_data.sectors_data)} sectors")
        
        # Create combined heightmap
        combined_map = create_combined_heightmap(
            terrain_data.sectors_data,
            self.sectors_x,
            self.sectors_y,
            terrain_data.grid_size
        )
        
        # Create Blender image - rotate texture for shader display
        terrain_data.heightmap_image = numpy_to_blender_image(combined_map, "TerrainHeightmap", rotate_texture=True)
        
        # Create plane mesh
        total_width = self.sectors_x * terrain_data.grid_size
        total_height = self.sectors_y * terrain_data.grid_size
        
        # Create mesh with subdivisions matching heightmap resolution
        bpy.ops.mesh.primitive_plane_add(
            size=2,
            location=(0, 0, 0),
            rotation=(0, 0, 3.14159)  # 180 degrees on Z axis (pi radians)
        )
        
        terrain_obj = context.active_object
        terrain_obj.name = "TerrainMesh"
        terrain_data.terrain_object = terrain_obj
        
        # Add subdivision
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.subdivide(number_cuts=max(total_width, total_height) - 1)
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Scale to match terrain dimensions
        terrain_obj.scale = (total_width / 2, total_height / 2, 1)
        
        # Create material with heightmap
        mat = bpy.data.materials.new(name="TerrainMaterial")
        mat.use_nodes = True
        terrain_obj.data.materials.append(mat)
        
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        
        # Create nodes
        output_node = nodes.new(type='ShaderNodeOutputMaterial')
        output_node.location = (400, 0)
        
        bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
        bsdf_node.location = (0, 0)
        
        tex_node = nodes.new(type='ShaderNodeTexImage')
        tex_node.location = (-400, 0)
        tex_node.image = terrain_data.heightmap_image
        
        # Connect nodes
        links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
        links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
        
        # Add Displacement Modifier
        displace_mod = terrain_obj.modifiers.new(name="HeightDisplacement", type='DISPLACE')
        
        # Create texture for displacement
        displace_tex = bpy.data.textures.new(name="TerrainDisplaceTex", type='IMAGE')
        displace_tex.image = terrain_data.heightmap_image
        displace_mod.texture = displace_tex
        displace_mod.strength = self.height_scale
        displace_mod.mid_level = 0
        
        # Add Subdivision Surface for smoother displacement
        subsurf_mod = terrain_obj.modifiers.new(name="Subdivision", type='SUBSURF')
        subsurf_mod.levels = 2
        subsurf_mod.render_levels = 2
        
        # Setup UV mapping (simple planar projection)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0)
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Rotate UVs 90 degrees counter-clockwise to match displacement
        mesh = terrain_obj.data
        uv_layer = mesh.uv_layers.active.data
        for loop in mesh.loops:
            uv = uv_layer[loop.index].uv
            # Rotate 90 degrees counter-clockwise around center (0.5, 0.5)
            x, y = uv.x - 0.5, uv.y - 0.5
            uv.x = -y + 0.5
            uv.y = x + 0.5
        
        # Switch to texture paint mode for editing
        context.view_layer.objects.active = terrain_obj
        
        self.report({'INFO'}, f"Terrain imported successfully! {total_width}x{total_height} resolution")
        return {'FINISHED'}

# Operator: Export terrain
class TERRAIN_OT_export(bpy.types.Operator):
    bl_idname = "terrain.export_csdat"
    bl_label = "Export CSDAT Terrain"
    bl_description = "Export edited terrain back to CSDAT files"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        global terrain_data
        
        if not terrain_data.heightmap_image:
            self.report({'ERROR'}, "No terrain image to export")
            return {'CANCELLED'}
        
        if not terrain_data.current_directory:
            self.report({'ERROR'}, "No directory set. Import terrain first")
            return {'CANCELLED'}
        
        # Get the current edited image
        edited_image = terrain_data.heightmap_image
        
        # Convert to numpy
        edited_array = blender_image_to_numpy(edited_image)
        
        # Undo transformations to get back to original sector layout:
        # 1. Undo the texture display rotation (90° CCW) = rotate 90° CW
        # 2. Undo the horizontal flip = flip horizontally again
        # 3. Undo the heightmap rotation (90° CCW) = rotate 90° CW
        edited_array = np.rot90(edited_array, k=-1)  # Undo texture rotation
        edited_array = np.fliplr(edited_array)        # Undo horizontal flip
        edited_array = np.rot90(edited_array, k=-1)  # Undo heightmap rotation
        
        # Get original min/max for denormalization
        all_heights = []
        for sector_data in terrain_data.sectors_data.values():
            all_heights.extend(sector_data.flatten())
        
        original_min = min(all_heights)
        original_max = max(all_heights)
        
        # Denormalize
        if original_max > original_min:
            denormalized = edited_array * (original_max - original_min) + original_min
        else:
            denormalized = edited_array * original_max
        
        # Split back into sectors and write
        sectors_written = 0
        sectors_failed = 0
        
        for display_row in range(terrain_data.sectors_y):
            for col in range(terrain_data.sectors_x):
                sector_row = terrain_data.sectors_y - 1 - display_row
                sector_index = sector_row * terrain_data.sectors_x + col
                
                # Extract sector data
                start_y = display_row * terrain_data.grid_size
                end_y = start_y + terrain_data.grid_size
                start_x = col * terrain_data.grid_size
                end_x = start_x + terrain_data.grid_size
                
                sector_data = denormalized[start_y:end_y, start_x:end_x]
                
                # Write to file
                file_path = os.path.join(
                    terrain_data.current_directory,
                    f"sd{sector_index}.csdat"
                )
                
                if os.path.exists(file_path):
                    if write_sector_to_file(file_path, sector_data, terrain_data.grid_size):
                        sectors_written += 1
                    else:
                        sectors_failed += 1
                        self.report({'WARNING'}, f"Failed to write sector {sector_index}")
        
        self.report({'INFO'}, f"Export complete! Written: {sectors_written}, Failed: {sectors_failed}")
        return {'FINISHED'}

# Panel in the 3D View sidebar
class TERRAIN_PT_main_panel(bpy.types.Panel):
    bl_label = "CSDAT Terrain Editor"
    bl_idname = "TERRAIN_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Terrain Editor'
    
    def draw(self, context):
        layout = self.layout
        
        # Import section
        box = layout.box()
        box.label(text="Import Terrain", icon='IMPORT')
        box.operator("terrain.import_csdat", text="Load CSDAT Files", icon='FILEBROWSER')
        
        # Info
        if terrain_data.current_directory:
            box.label(text=f"Directory: ...{os.path.basename(terrain_data.current_directory)}")
            box.label(text=f"Sectors loaded: {len(terrain_data.sectors_data)}")
            box.label(text=f"Grid: {terrain_data.sectors_x}x{terrain_data.sectors_y}")
        else:
            box.label(text="No terrain loaded", icon='ERROR')
        
        layout.separator()
        
        # Export section
        box = layout.box()
        box.label(text="Export Terrain", icon='EXPORT')
        
        if terrain_data.heightmap_image:
            box.operator("terrain.export_csdat", text="Save to CSDAT Files", icon='FILE_TICK')
            box.label(text="⚠️ This overwrites existing files!", icon='ERROR')
        else:
            box.label(text="Import terrain first", icon='INFO')
        
        layout.separator()
        
        # Texture Paint hint
        box = layout.box()
        box.label(text="Editing Tips:", icon='BRUSH_DATA')
        box.label(text="• Switch to Texture Paint mode")
        box.label(text="• Paint in grayscale")
        box.label(text="• White = high, Black = low")
        box.label(text="• Use Image Editor to see texture")

# Registration
classes = (
    TERRAIN_OT_import,
    TERRAIN_OT_export,
    TERRAIN_PT_main_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()