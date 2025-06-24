#!/usr/bin/env python3
"""
Direct glTF export from OpenEQ Zone objects
Bypasses the intermediate .oez format for faster conversion

Coordinate System Transformation:
- EverQuest uses Z-up coordinate system (like 3ds Max, Blender)
- glTF uses Y-up coordinate system (industry standard)
- Transformation: (x, y, z) -> (x, z, -y) for positions and normals
"""

import json
import base64
import struct
import tempfile
import math
from typing import Dict, List, Any, Optional, Tuple
import os
import sys
import io
from PIL import Image


def create_texture_atlases(
    textures_dict: Dict[str, bytes], texture_flags: Dict[str, int]
) -> Dict[str, Dict]:
    """
    Create texture atlases by grouping compatible textures together.
    This dramatically reduces the number of texture uniforms needed.

    Returns:
        Dict mapping atlas_id to atlas data containing:
        - png_data: Combined atlas image as PNG bytes
        - texture_mapping: Maps texture names to UV transform info
        - atlas_size: Dimensions of the atlas
        - textures: List of texture names in this atlas
    """
    if not textures_dict:
        return {}

    print(f"Analyzing {len(textures_dict)} textures for atlasing...")

    # Group textures by compatibility (flags, alpha requirements)
    texture_groups = {}
    processed_textures = {}

    for texture_name, texture_data in textures_dict.items():
        try:
            # Load and analyze texture
            image = Image.open(io.BytesIO(texture_data))
            flags = texture_flags.get(texture_name, 0)

            # Convert to standard format
            if image.mode != "RGBA":
                image = image.convert("RGBA")

            # Apply color-key transparency for masked textures
            if flags & 0x1:  # FLAG_MASKED
                image = apply_color_key_transparency(image)

            # Group by material properties for atlas compatibility
            # Textures with different transparency needs go in different atlases
            alpha_mode = "opaque"
            if flags & 0x1:  # FLAG_MASKED
                alpha_mode = "mask"
            elif flags & 0x2:  # FLAG_TRANSLUCENT
                alpha_mode = "blend"
            elif flags & 0x4:  # FLAG_TRANSPARENT
                alpha_mode = "blend"

            # Determine atlas group based on texture properties
            group_key = (alpha_mode, flags & 0x7)  # Group by transparency flags

            if group_key not in texture_groups:
                texture_groups[group_key] = []

            # Store processed texture info
            processed_textures[texture_name] = {
                "image": image,
                "flags": flags,
                "alpha_mode": alpha_mode,
                "size": image.size,
            }

            texture_groups[group_key].append(texture_name)

        except Exception as e:
            print(f"Warning: Failed to process texture {texture_name}: {e}")
            continue

    print(f"Grouped textures into {len(texture_groups)} compatibility groups")

    # Create atlases for each group
    atlases = {}
    atlas_counter = 0

    for group_key, texture_names in texture_groups.items():
        alpha_mode, flags = group_key

        # Split large groups into multiple atlases to avoid oversized images
        max_textures_per_atlas = 16  # Balance between efficiency and atlas size

        for i in range(0, len(texture_names), max_textures_per_atlas):
            batch_textures = texture_names[i : i + max_textures_per_atlas]

            if len(batch_textures) == 1:
                # Single texture - no atlasing needed, but still process for consistency
                texture_name = batch_textures[0]
                texture_info = processed_textures[texture_name]

                # Save as individual atlas
                png_buffer = io.BytesIO()
                texture_info["image"].save(png_buffer, format="PNG", optimize=True)
                png_data = png_buffer.getvalue()

                atlas_id = f"atlas_{atlas_counter}"
                atlases[atlas_id] = {
                    "png_data": png_data,
                    "atlas_size": texture_info["size"],
                    "textures": [texture_name],
                    "texture_mapping": {
                        texture_name: {
                            "atlas_id": atlas_id,
                            "u_offset": 0.0,
                            "v_offset": 0.0,
                            "u_scale": 1.0,
                            "v_scale": 1.0,
                        }
                    },
                }
                atlas_counter += 1
                continue

            # Create actual atlas for multiple textures
            atlas_id = f"atlas_{atlas_counter}"
            atlas_data = pack_textures_into_atlas(
                batch_textures, processed_textures, atlas_id
            )

            if atlas_data:
                atlases[atlas_id] = atlas_data
                print(
                    f"  Atlas {atlas_id}: {len(batch_textures)} textures ({alpha_mode} mode)"
                )

            atlas_counter += 1

    print(
        f"Created {len(atlases)} texture atlases (reduced from {len(textures_dict)} individual textures)"
    )
    return atlases


def apply_color_key_transparency(image: Image.Image) -> Image.Image:
    """Apply color-key transparency using the first pixel as the transparent color"""
    pixels = list(image.getdata())
    if not pixels:
        return image

    # Get the first pixel (top-left corner) as color-key
    color_key_r, color_key_g, color_key_b, _ = pixels[0]
    new_pixels = []

    for r, g, b, a in pixels:
        # Check if pixel matches color-key (with small tolerance for compression artifacts)
        if (
            abs(r - color_key_r) <= 2
            and abs(g - color_key_g) <= 2
            and abs(b - color_key_b) <= 2
        ):
            new_pixels.append((r, g, b, 0))  # Make transparent
        else:
            new_pixels.append((r, g, b, 255))  # Keep opaque

    image.putdata(new_pixels)
    return image


def pack_textures_into_atlas(
    texture_names: List[str], processed_textures: Dict, atlas_id: str
) -> Optional[Dict]:
    """Pack multiple textures into a single atlas image using simple grid layout"""
    try:
        # Calculate optimal grid layout
        num_textures = len(texture_names)
        grid_size = math.ceil(math.sqrt(num_textures))

        # Find maximum texture dimensions for grid cell size
        max_width = max_height = 0
        for texture_name in texture_names:
            w, h = processed_textures[texture_name]["size"]
            max_width = max(max_width, w)
            max_height = max(max_height, h)

        # Create atlas image
        atlas_width = grid_size * max_width
        atlas_height = grid_size * max_height

        # Limit atlas size to prevent WebGL texture size limits
        max_atlas_size = 2048
        if atlas_width > max_atlas_size or atlas_height > max_atlas_size:
            # Reduce grid size and warn
            grid_size = min(grid_size, max_atlas_size // max(max_width, max_height, 1))
            atlas_width = grid_size * max_width
            atlas_height = grid_size * max_height
            print(f"Warning: Limited atlas size to {atlas_width}x{atlas_height}")

        # Create atlas with transparent background
        atlas_image = Image.new("RGBA", (atlas_width, atlas_height), (0, 0, 0, 0))

        # Pack textures and build mapping
        texture_mapping = {}
        for i, texture_name in enumerate(texture_names):
            if i >= grid_size * grid_size:
                print(f"Warning: Too many textures for atlas, skipping {texture_name}")
                continue

            row = i // grid_size
            col = i % grid_size

            # Calculate position in atlas
            x_offset = col * max_width
            y_offset = row * max_height

            # Get texture image
            texture_image = processed_textures[texture_name]["image"]

            # Center texture in cell if smaller than max size
            tex_w, tex_h = texture_image.size
            center_x = x_offset + (max_width - tex_w) // 2
            center_y = y_offset + (max_height - tex_h) // 2

            # Paste texture into atlas
            atlas_image.paste(texture_image, (center_x, center_y))

            # Calculate UV transformation for this texture
            u_offset = center_x / atlas_width
            v_offset = center_y / atlas_height
            u_scale = tex_w / atlas_width
            v_scale = tex_h / atlas_height

            texture_mapping[texture_name] = {
                "atlas_id": atlas_id,
                "u_offset": u_offset,
                "v_offset": v_offset,
                "u_scale": u_scale,
                "v_scale": v_scale,
            }

        # Convert to PNG
        png_buffer = io.BytesIO()
        atlas_image.save(png_buffer, format="PNG", optimize=True)
        png_data = png_buffer.getvalue()

        return {
            "png_data": png_data,
            "atlas_size": (atlas_width, atlas_height),
            "textures": texture_names,
            "texture_mapping": texture_mapping,
        }

    except Exception as e:
        print(f"Error creating atlas {atlas_id}: {e}")
        return None


def export_zone_to_gltf(zone, output_path: str, textures_dict: Dict[str, bytes] = None):
    # Calculate zone bounding box for consistent centering
    zone_min = [float("inf"), float("inf"), float("inf")]
    zone_max = [float("-inf"), float("-inf"), float("-inf")]

    # Calculate bounding box from all meshes (except skybox)
    for obj in zone.objects:
        for mesh in obj.meshes:
            positions = mesh.vertbuffer.data
            # Process positions in groups of 8 (pos(3) + normal(3) + texcoord(2))
            for i in range(0, len(positions), 8):
                x, y, z = positions[i], positions[i + 1], positions[i + 2]
                # Apply Z-up to Y-up transformation for bounding box calculation
                world_x, world_y, world_z = x, z, -y

                zone_min[0] = min(zone_min[0], world_x)
                zone_min[1] = min(zone_min[1], world_y)
                zone_min[2] = min(zone_min[2], world_z)
                zone_max[0] = max(zone_max[0], world_x)
                zone_max[1] = max(zone_max[1], world_y)
                zone_max[2] = max(zone_max[2], world_z)

    zone_center = [
        (zone_min[0] + zone_max[0]) / 2,
        (zone_min[1] + zone_max[1]) / 2,
        (zone_min[2] + zone_max[2]) / 2,
    ]

    print(f"Zone bounding box: min={zone_min}, max={zone_max}")
    print(f"Zone center offset: {zone_center}")
    """
    Export Zone object directly to glTF format without intermediate .oez step

    Args:
        zone: Zone object from zonefile.py
        output_path: Path for output .glb file
        textures_dict: Dictionary of texture name -> texture data
    """
    # First coalesce meshes like the original output method
    zone.coalesceObjectMeshes()

    # Collect all textures from materials with their flags
    if textures_dict is None:
        textures_dict = {}

    # Track material flags for each texture to handle transparency correctly
    texture_flags = {}

    # Collect texture data from all materials
    for obj in zone.objects:
        for mesh in obj.meshes:
            # INVISIBLE WALLS: Skip FLAG_TRANSPARENT materials from glTF export
            # These are zone boundary collision walls that render as colored barriers
            # They're preserved in zone data for collision detection but excluded from visual rendering
            # TODO: Consider adding command-line option to include collision geometry for game engines
            if mesh.material.flags & 0x4:  # FLAG_TRANSPARENT (all invisible walls)
                continue

            material = mesh.material
            for i, filename in enumerate(material.filenames):
                if filename not in textures_dict and i < len(material.textures):
                    textures_dict[filename] = material.textures[i]
                    # Store the material flags for this texture
                    texture_flags[filename] = material.flags

    # Create glTF structure with lighting extension support
    gltf = {
        "asset": {"version": "2.0", "generator": "OpenEQ Direct Converter"},
        "scenes": [{"nodes": []}],
        "scene": 0,
        "nodes": [],
        "meshes": [],
        "materials": [],
        "textures": [],
        "images": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
        "extensionsUsed": ["KHR_lights_punctual"],
        "extensions": {"KHR_lights_punctual": {"lights": []}},
    }

    # Binary data buffer
    binary_data = bytearray()

    # Process lights from EverQuest data
    print(f"Processing {len(zone.lights)} lights from EverQuest data...")

    for light_index, light in enumerate(zone.lights):
        # Transform position from Z-up to Y-up coordinate system
        pos_x, pos_y, pos_z = light.position
        light_position = [pos_x, pos_z, -pos_y]

        # Use original coordinates like mesh vertices and placeables - no centering offset

        # Convert EverQuest light to glTF KHR_lights_punctual format
        # EverQuest light color is RGB (0-1 range)
        light_color = list(light.color)

        # Convert EverQuest attenuation to glTF intensity
        # EverQuest uses distance-based attenuation, glTF uses intensity + range
        # Approximate intensity based on attenuation and radius
        intensity = max(
            1.0, light.attenuation / 100.0
        )  # Scale attenuation to reasonable intensity
        light_range = light.radius

        # Add KHR_lights_punctual light definition
        gltf_light = {
            "type": "point",
            "color": light_color,
            "intensity": intensity,
            "range": light_range,
            "name": f"EQLight_{light_index}",
        }

        light_def_index = len(gltf["extensions"]["KHR_lights_punctual"]["lights"])
        gltf["extensions"]["KHR_lights_punctual"]["lights"].append(gltf_light)

        # Create a node for this light
        light_node_index = len(gltf["nodes"])
        gltf["scenes"][0]["nodes"].append(light_node_index)

        gltf["nodes"].append(
            {
                "name": f"LightNode_{light_index}",
                "translation": light_position,
                "extensions": {"KHR_lights_punctual": {"light": light_def_index}},
            }
        )

        # Debug output for lighting
        print(
            f"Light {light_index}: pos={light_position}, color={light_color}, intensity={intensity:.2f}, range={light_range:.2f}"
        )

    # TEXTURE PROCESSING: Individual textures (temporary revert from atlasing)
    print("Processing individual textures (atlasing disabled for debugging)...")

    # Process individual textures like the original approach
    image_map = {}
    texture_atlas_map = {}  # Keep empty for now

    # Convert individual textures to images
    for texture_name, texture_data in textures_dict.items():
        try:
            # Convert texture data to PNG
            png_data = convert_texture_to_png(
                texture_data, texture_name, texture_flags.get(texture_name, 0)
            )

            image_index = len(gltf["images"])
            image_map[texture_name] = image_index

            # Add to binary buffer
            buffer_view_index = len(gltf["bufferViews"])
            start_pos = len(binary_data)
            binary_data.extend(png_data)

            gltf["images"].append(
                {"mimeType": "image/png", "bufferView": buffer_view_index}
            )

            gltf["bufferViews"].append(
                {"buffer": 0, "byteOffset": start_pos, "byteLength": len(png_data)}
            )

            gltf["textures"].append({"source": image_index})

        except Exception as e:
            print(f"Warning: Failed to process texture {texture_name}: {e}")
            continue

    print(f"Processed {len(image_map)} individual textures")

    # Process materials with atlas mapping
    material_map = {}
    for obj in zone.objects:
        for mesh in obj.meshes:
            # INVISIBLE WALLS: Skip FLAG_TRANSPARENT materials from material processing
            # These zone boundary walls would render as visible colored barriers in viewers
            # Better to exclude entirely than try to make them transparent in Three.js
            if mesh.material.flags & 0x4:  # FLAG_TRANSPARENT (all invisible walls)
                continue

            material = mesh.material

            mat_key = (material.flags, material.param, material.filenames)

            if mat_key not in material_map:
                mat_index = len(gltf["materials"])
                material_map[mat_key] = mat_index

                gltf_material = {
                    "name": f"Material_{mat_index}",
                    "pbrMetallicRoughness": {
                        "metallicFactor": 0.0,
                        "roughnessFactor": 1.0,
                    },
                }

                # Add individual texture if available
                if material.filenames:
                    texture_name = material.filenames[0]
                    if texture_name in image_map:
                        texture_index = image_map[texture_name]
                        gltf_material["pbrMetallicRoughness"]["baseColorTexture"] = {
                            "index": texture_index
                        }

                # Handle transparency - match zonefile.py flag definitions
                # FLAG_MASKED = 1 << 0 = 1 (alpha testing for cutout materials like foliage)
                # FLAG_TRANSLUCENT = 1 << 1 = 2 (alpha blending for translucent materials)
                # FLAG_TRANSPARENT = 1 << 2 = 4 (fully transparent)
                if material.flags & 0x1:  # FLAG_MASKED - use alpha testing for cutout
                    gltf_material["alphaMode"] = "MASK"
                    gltf_material["alphaCutoff"] = 0.5
                elif material.flags & 0x2:  # FLAG_TRANSLUCENT - use blending
                    gltf_material["alphaMode"] = "BLEND"
                elif material.flags & 0x4:  # FLAG_TRANSPARENT - use blending
                    gltf_material["alphaMode"] = "BLEND"

                # Special handling for skybox materials
                if "sky" in gltf_material["name"].lower():
                    # Skybox materials should not write to depth buffer and should be double-sided
                    gltf_material["doubleSided"] = True
                    # Add extension for depth write control if needed
                    if gltf_material.get("alphaMode") == "BLEND":
                        # For transparent skybox layers (clouds), ensure proper rendering
                        pass

                gltf["materials"].append(gltf_material)

    # Process meshes and create nodes
    # Process skybox first (render behind everything)
    skybox_node_added = False

    # Create a mapping from objects to their mesh indices for instancing
    object_to_mesh = {}

    # NEW: Batch meshes by material to reduce draw calls and uniform usage
    # This is the key optimization to prevent "too many uniforms" errors
    print("Batching meshes by material to optimize draw calls...")

    # Batch meshes within each object to preserve placeable instances
    # Each object gets ONE mesh with multiple primitives (one per material)
    print("Creating optimized meshes with batched primitives per object...")

    for obj_index, obj in enumerate(zone.objects):
        if not obj.meshes:
            continue

        # Handle skybox specially - render it first and behind everything
        is_skybox = obj.name == "_SKYBOX_"

        # Group meshes by material within this specific object only
        obj_material_groups = {}

        for mesh in obj.meshes:
            # Skip invisible walls
            if mesh.material.flags & 0x4:  # FLAG_TRANSPARENT (invisible walls)
                continue

            mat_key = (
                mesh.material.flags,
                mesh.material.param,
                mesh.material.filenames,
            )

            if mat_key not in obj_material_groups:
                obj_material_groups[mat_key] = []

            obj_material_groups[mat_key].append(mesh)

        if not obj_material_groups:
            continue

        print(
            f"Object {obj_index} ({obj.name}): {len(obj_material_groups)} material groups, {sum(len(group) for group in obj_material_groups.values())} meshes"
        )

        # Create ONE mesh for this object with multiple primitives (one per material group)
        gltf_mesh_primitives = []

        # Process each material group within this object as a batched primitive
        for mat_key, mesh_group in obj_material_groups.items():
            if len(mesh_group) > 1:
                print(
                    f"  Batching {len(mesh_group)} meshes for material {material_map[mat_key]}"
                )

            # Combine all vertex data for this material within this object
            combined_positions = []
            combined_normals = []
            combined_texcoords = []
            combined_indices = []
            vertex_offset = 0

            for mesh in mesh_group:
                # Get vertex data for this mesh
                vertices = mesh.vertbuffer.data
                num_vertices = len(mesh.vertbuffer)

                # Extract and transform vertex data
                mesh_positions = []
                mesh_normals = []
                mesh_texcoords = []

                for i in range(num_vertices):
                    base_idx = i * mesh.vertbuffer.stride

                    # Original EQ coordinates (Z-up)
                    x, y, z = vertices[base_idx : base_idx + 3]
                    nx, ny, nz = vertices[base_idx + 3 : base_idx + 6]
                    u, v = vertices[base_idx + 6 : base_idx + 8]

                    # Transform Z-up to Y-up: (x, y, z) -> (x, z, -y)
                    # Use original coordinates like legacy .NET code - no centering
                    mesh_positions.extend([x, z, -y])
                    mesh_normals.extend([nx, nz, -ny])

                    # Standard UV coordinates with EverQuest V-flip
                    mesh_texcoords.extend([u, 1.0 - v])

                # Add to combined buffers
                combined_positions.extend(mesh_positions)
                combined_normals.extend(mesh_normals)
                combined_texcoords.extend(mesh_texcoords)

                # Convert polygons to indices with vertex offset
                for poly in mesh.polygons:
                    combined_indices.extend(
                        [
                            poly[0] + vertex_offset,
                            poly[2] + vertex_offset,
                            poly[1] + vertex_offset,
                        ]
                    )

                vertex_offset += num_vertices

            # Create buffer data for the batched primitive
            if not combined_positions:
                continue

            # Add combined vertex data to binary buffer
            pos_buffer_start = len(binary_data)
            pos_data = struct.pack(
                "<" + "f" * len(combined_positions), *combined_positions
            )
            binary_data.extend(pos_data)

            normal_buffer_start = len(binary_data)
            normal_data = struct.pack(
                "<" + "f" * len(combined_normals), *combined_normals
            )
            binary_data.extend(normal_data)

            texcoord_buffer_start = len(binary_data)
            texcoord_data = struct.pack(
                "<" + "f" * len(combined_texcoords), *combined_texcoords
            )
            binary_data.extend(texcoord_data)

            # Add combined index data to binary buffer
            index_buffer_start = len(binary_data)
            index_data = struct.pack(
                "<" + "I" * len(combined_indices), *combined_indices
            )
            binary_data.extend(index_data)

            # Create buffer views for batched primitive
            pos_buffer_view = len(gltf["bufferViews"])
            gltf["bufferViews"].append(
                {
                    "buffer": 0,
                    "byteOffset": pos_buffer_start,
                    "byteLength": len(pos_data),
                    "target": 34962,  # ARRAY_BUFFER
                }
            )

            normal_buffer_view = len(gltf["bufferViews"])
            gltf["bufferViews"].append(
                {
                    "buffer": 0,
                    "byteOffset": normal_buffer_start,
                    "byteLength": len(normal_data),
                    "target": 34962,  # ARRAY_BUFFER
                }
            )

            texcoord_buffer_view = len(gltf["bufferViews"])
            gltf["bufferViews"].append(
                {
                    "buffer": 0,
                    "byteOffset": texcoord_buffer_start,
                    "byteLength": len(texcoord_data),
                    "target": 34962,  # ARRAY_BUFFER
                }
            )

            index_buffer_view = len(gltf["bufferViews"])
            gltf["bufferViews"].append(
                {
                    "buffer": 0,
                    "byteOffset": index_buffer_start,
                    "byteLength": len(index_data),
                    "target": 34963,  # ELEMENT_ARRAY_BUFFER
                }
            )

            # Create accessors for batched primitive
            total_vertices = len(combined_positions) // 3

            pos_accessor = len(gltf["accessors"])
            gltf["accessors"].append(
                {
                    "bufferView": pos_buffer_view,
                    "componentType": 5126,  # FLOAT
                    "count": total_vertices,
                    "type": "VEC3",
                    "min": [min(combined_positions[i::3]) for i in range(3)],
                    "max": [max(combined_positions[i::3]) for i in range(3)],
                }
            )

            normal_accessor = len(gltf["accessors"])
            gltf["accessors"].append(
                {
                    "bufferView": normal_buffer_view,
                    "componentType": 5126,  # FLOAT
                    "count": total_vertices,
                    "type": "VEC3",
                }
            )

            texcoord_accessor = len(gltf["accessors"])
            gltf["accessors"].append(
                {
                    "bufferView": texcoord_buffer_view,
                    "componentType": 5126,  # FLOAT
                    "count": total_vertices,
                    "type": "VEC2",
                }
            )

            index_accessor = len(gltf["accessors"])
            gltf["accessors"].append(
                {
                    "bufferView": index_buffer_view,
                    "componentType": 5125,  # UNSIGNED_INT
                    "count": len(combined_indices),
                    "type": "SCALAR",
                }
            )

            # Create batched primitive for this material within this object
            material_index = material_map[mat_key]
            batched_primitive = {
                "attributes": {
                    "POSITION": pos_accessor,
                    "NORMAL": normal_accessor,
                    "TEXCOORD_0": texcoord_accessor,
                },
                "indices": index_accessor,
                "material": material_index,
            }

            gltf_mesh_primitives.append(batched_primitive)

            total_triangles = len(combined_indices) // 3
            if len(mesh_group) > 1:
                print(
                    f"    Created batched primitive with {total_vertices} vertices, {total_triangles} triangles"
                )

        # Create ONE mesh for this object with all its batched primitives
        if gltf_mesh_primitives:
            mesh_index = len(gltf["meshes"])
            gltf["meshes"].append(
                {
                    "name": obj.name or f"Object_{obj_index}",
                    "primitives": gltf_mesh_primitives,
                }
            )

            # Store mapping for instancing placeables (ONE mapping per object)
            object_to_mesh[obj] = mesh_index

            # Create node for the base object (zone terrain, skybox, etc.)
            # Only create base nodes for zone objects (index 0) and skybox
            if obj_index == 0 or is_skybox:
                node_index = len(gltf["nodes"])

                if is_skybox and not skybox_node_added:
                    # Insert skybox node at the beginning
                    gltf["scenes"][0]["nodes"].insert(0, node_index)
                    skybox_node_added = True
                else:
                    gltf["scenes"][0]["nodes"].append(node_index)

                gltf["nodes"].append(
                    {
                        "name": obj.name or f"Node_{obj_index}",
                        "mesh": mesh_index,
                    }
                )

            print(
                f"  Created complete mesh with {len(gltf_mesh_primitives)} primitives for object {obj.name}"
            )

    print(f"Object-based mesh batching complete: {len(gltf['meshes'])} meshes created")
    print(
        f"Preserved one-to-one object-to-mesh mapping for correct placeable instancing"
    )

    # Process placeables to create positioned instances of objects
    print(f"Processing {len(zone.placeables)} placeables...")

    for placeable_index, placeable in enumerate(zone.placeables):
        if placeable.obj not in object_to_mesh:
            print(f"Warning: Placeable references unknown object: {placeable.obj.name}")
            continue

        mesh_index = object_to_mesh[placeable.obj]

        # Convert EverQuest transform to glTF transform
        # Position: Z-up to Y-up transformation
        pos_x, pos_y, pos_z = placeable.position
        position = [pos_x, pos_z, -pos_y]

        # Use original coordinates like legacy .NET code - no centering for placeables
        # The legacy .NET code uses inst.Position directly without any offset

        # Scale: EverQuest uses uniform scale, but we store as 3D vector
        if isinstance(placeable.scale, (tuple, list)) and len(placeable.scale) == 3:
            scale = list(placeable.scale)
        else:
            # Handle scalar scale
            scale_value = placeable.scale if hasattr(placeable, "scale") else 1.0
            scale = [scale_value, scale_value, scale_value]

        # Rotation: Convert from EverQuest Z-up coordinate system to glTF Y-up
        # EverQuest: X=right, Y=forward, Z=up
        # glTF: X=right, Y=up, Z=back
        # Transformation: (rot_x, rot_y, rot_z) -> (rot_x, rot_z, -rot_y)
        rot_x, rot_y, rot_z = placeable.rotation

        # Apply coordinate system transformation to Euler angles
        eq_rot_x = rot_x  # X rotation stays the same
        eq_rot_y = rot_z  # EverQuest Z rotation becomes glTF Y rotation
        eq_rot_z = -rot_y  # EverQuest Y rotation becomes glTF -Z rotation

        # Convert Euler angles to quaternion (ZYX order for glTF)
        # Use half angles for quaternion conversion
        cx, sx = math.cos(eq_rot_x * 0.5), math.sin(eq_rot_x * 0.5)
        cy, sy = math.cos(eq_rot_y * 0.5), math.sin(eq_rot_y * 0.5)
        cz, sz = math.cos(eq_rot_z * 0.5), math.sin(eq_rot_z * 0.5)

        # Quaternion from Euler angles (XYZ rotation order)
        qw = cx * cy * cz + sx * sy * sz
        qx = sx * cy * cz - cx * sy * sz
        qy = cx * sy * cz + sx * cy * sz
        qz = cx * cy * sz - sx * sy * cz

        rotation = [qx, qy, qz, qw]

        # Create node for this instance
        instance_node_index = len(gltf["nodes"])
        gltf["scenes"][0]["nodes"].append(instance_node_index)

        gltf["nodes"].append(
            {
                "name": f"{placeable.obj.name}_instance_{placeable_index}",
                "mesh": mesh_index,
                "translation": position,
                "rotation": rotation,
                "scale": scale,
            }
        )

    print(f"Created {len(zone.placeables)} object instances")

    # Add buffer
    gltf["buffers"].append({"byteLength": len(binary_data)})

    # Write GLB file
    write_glb(gltf, binary_data, output_path)
    print(f"Exported glTF to: {output_path}")


def convert_texture_to_png(
    texture_data: bytes, texture_name: str, material_flags: int = 0
) -> bytes:
    """Convert texture data to PNG format, creating alpha channels for color-keyed transparency"""
    try:
        # Try to open as image
        image = Image.open(io.BytesIO(texture_data))

        # Convert to RGBA to handle transparency
        if image.mode != "RGBA":
            image = image.convert("RGBA")

        # For masked materials, convert color-key transparency to alpha
        # Use first pixel (top-left corner) as the transparent color-key
        if material_flags & 0x1:  # FLAG_MASKED
            pixels = list(image.getdata())

            if pixels:
                # Get the first pixel (top-left corner) as color-key
                color_key_r, color_key_g, color_key_b, _ = pixels[0]
                new_pixels = []
                transparent_count = 0

                for r, g, b, a in pixels:
                    # Check if pixel matches color-key (with small tolerance for compression artifacts)
                    if (
                        abs(r - color_key_r) <= 2
                        and abs(g - color_key_g) <= 2
                        and abs(b - color_key_b) <= 2
                    ):
                        new_pixels.append((r, g, b, 0))  # Make transparent
                        transparent_count += 1
                    else:
                        new_pixels.append((r, g, b, 255))  # Keep opaque

                if transparent_count > 0:
                    image.putdata(new_pixels)
                    # Only show if significant transparency was created
                    if transparent_count > 100:  # Arbitrary threshold for "significant"
                        print(
                            f"Texture: Created alpha channel ({transparent_count} transparent pixels)"
                        )
                # Skip message for textures without matching color-key pixels

        # Save as PNG
        png_buffer = io.BytesIO()
        image.save(png_buffer, format="PNG", optimize=True)

        # Check for alpha variation (debug info - only show when interesting)
        extrema = image.getextrema()
        if len(extrema) == 4:  # RGBA
            alpha_min, alpha_max = extrema[3]
            if alpha_min < 255:
                print(f"Texture: Alpha range {alpha_min}-{alpha_max}")
            # Skip "fully opaque" messages to reduce verbosity

        return png_buffer.getvalue()

    except Exception as e:
        print(f"Warning: Failed to convert texture {texture_name}: {e}")
        # Create gray placeholder with alpha
        placeholder = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
        png_buffer = io.BytesIO()
        placeholder.save(png_buffer, format="PNG")
        return png_buffer.getvalue()


def write_glb(gltf: Dict[str, Any], binary_data: bytearray, output_path: str):
    """Write glTF data as GLB binary file"""

    # Convert glTF to JSON bytes
    json_data = json.dumps(gltf, separators=(",", ":")).encode("utf-8")

    # Pad JSON to 4-byte boundary
    json_padding = (4 - (len(json_data) % 4)) % 4
    json_data += b" " * json_padding

    # Pad binary data to 4-byte boundary
    bin_padding = (4 - (len(binary_data) % 4)) % 4
    binary_data.extend(b"\x00" * bin_padding)

    # Calculate sizes
    json_chunk_size = len(json_data)
    bin_chunk_size = len(binary_data)
    total_size = 12 + 8 + json_chunk_size + 8 + bin_chunk_size

    with open(output_path, "wb") as f:
        # GLB header
        f.write(b"glTF")  # Magic
        f.write(struct.pack("<I", 2))  # Version
        f.write(struct.pack("<I", total_size))  # Total length

        # JSON chunk
        f.write(struct.pack("<I", json_chunk_size))  # Chunk length
        f.write(b"JSON")  # Chunk type
        f.write(json_data)

        # Binary chunk
        f.write(struct.pack("<I", bin_chunk_size))  # Chunk length
        f.write(b"BIN\x00")  # Chunk type
        f.write(binary_data)
