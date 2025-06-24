#!/usr/bin/env python3
"""
EverQuest Sky Processing Module

Handles parsing and processing of EverQuest sky data from sky.s3d and sky.wld files.
Supports the multi-layer sky system with upper sky, lower clouds, and celestial objects.
"""

import os
import math
from typing import Dict, List, Tuple, Optional, Any
from s3d import readS3D
from wld import Wld
from zonefile import VertexBuffer, Material, Mesh
from utility import flatten, interleave


class SkyDome:
    """Represents a sky dome with textures and geometry"""

    def __init__(self, name: str):
        self.name = name
        self.upper_sky_texture = None  # Main sky texture
        self.lower_cloud_texture = None  # Cloud layer texture
        self.sun_texture = None
        self.moon_texture = None
        self.celestial_textures = []  # Additional celestial bodies
        self.dome_type = "hemisphere"  # "hemisphere" or "sphere"

    def __repr__(self):
        return f"SkyDome(name='{self.name}', upper={self.upper_sky_texture}, lower={self.lower_cloud_texture})"


class SkyProcessor:
    """Processes EverQuest sky files and generates skybox geometry"""

    def __init__(self, eqdata_path: str):
        self.eqdata_path = eqdata_path
        self.sky_s3d_path = os.path.join(eqdata_path, "sky.s3d")
        self.sky_files = None
        self.sky_wld = None
        self.available_skies = {}

    def load_sky_data(self) -> bool:
        """Load sky.s3d and sky.wld files"""
        try:
            if not os.path.exists(self.sky_s3d_path):
                print(f"Sky file not found: {self.sky_s3d_path}")
                return False

            print("Loading sky data...")
            self.sky_files = readS3D(open(self.sky_s3d_path, "rb"))

            if "sky.wld" in self.sky_files:
                self.sky_wld = Wld(self.sky_files["sky.wld"], self.sky_files)
                print(f"Loaded sky.wld with {len(self.sky_wld.frags)} fragments")
                self._analyze_sky_fragments()
            else:
                print("Warning: sky.wld not found in sky.s3d")

            self._categorize_sky_textures()
            return True

        except Exception as e:
            print(f"Error loading sky data: {e}")
            return False

    def _analyze_sky_fragments(self):
        """Analyze WLD fragments in sky.wld to understand structure"""
        if not self.sky_wld:
            return

        print(f"Sky WLD fragment types: {sorted(self.sky_wld.byType.keys())}")

        # Look for sky-specific fragments
        for frag_type, frags in self.sky_wld.byType.items():
            if frags:
                print(f"  Fragment type 0x{frag_type:02X}: {len(frags)} instances")

                # Show fragment names for debugging
                for i, frag in enumerate(frags[:3]):  # Show first 3 of each type
                    if hasattr(frag, "_name") and frag._name:
                        print(f"    [{i}] {frag._name}")
                    elif isinstance(frag, dict) and "_name" in frag:
                        print(f"    [{i}] {frag['_name']}")
                if len(frags) > 3:
                    print(f"    ... and {len(frags) - 3} more")

    def _categorize_sky_textures(self):
        """Categorize available sky textures by type"""
        if not self.sky_files:
            return

        sky_categories = {
            "normal": [],
            "desert": [],
            "luclin": [],
            "plane": [],  # Plane of various elements
            "clouds": [],
            "celestial": [],
        }

        for filename in self.sky_files.keys():
            if not filename.lower().endswith((".bmp", ".tga", ".dds")):
                continue

            name_lower = filename.lower()

            if "normal" in name_lower:
                sky_categories["normal"].append(filename)
            elif "desert" in name_lower:
                sky_categories["desert"].append(filename)
            elif "luclin" in name_lower:
                sky_categories["luclin"].append(filename)
            elif any(plane in name_lower for plane in ["po", "plane"]):
                sky_categories["plane"].append(filename)
            elif "cloud" in name_lower:
                sky_categories["clouds"].append(filename)
            elif any(
                celestial in name_lower
                for celestial in ["sun", "moon", "saturn", "star"]
            ):
                sky_categories["celestial"].append(filename)

        print("Sky texture categories:")
        for category, textures in sky_categories.items():
            if textures:
                print(f"  {category}: {len(textures)} textures")
                for tex in textures[:3]:  # Show first 3
                    print(f"    {tex}")
                if len(textures) > 3:
                    print(f"    ... and {len(textures) - 3} more")

        self.sky_categories = sky_categories

    def get_default_skybox(self) -> Optional[SkyDome]:
        """Get a default skybox configuration"""
        if not self.sky_files:
            return None

        # Try to create a basic skybox using available textures
        skybox = SkyDome("default")

        # Look for normal sky textures first
        if "normalsky.bmp" in self.sky_files:
            skybox.upper_sky_texture = "normalsky.bmp"
        elif "luclinsky1.bmp" in self.sky_files:
            skybox.upper_sky_texture = "luclinsky1.bmp"
        elif self.sky_categories.get("normal"):
            skybox.upper_sky_texture = self.sky_categories["normal"][0]

        # Look for cloud textures
        if "normalcloud.bmp" in self.sky_files:
            skybox.lower_cloud_texture = "normalcloud.bmp"
        elif "fluffycloud.bmp" in self.sky_files:
            skybox.lower_cloud_texture = "fluffycloud.bmp"
        elif self.sky_categories.get("clouds"):
            skybox.lower_cloud_texture = self.sky_categories["clouds"][0]

        # Look for celestial objects
        if "sun.bmp" in self.sky_files:
            skybox.sun_texture = "sun.bmp"
        if "moon.bmp" in self.sky_files:
            skybox.moon_texture = "moon.bmp"

        return skybox

    def generate_skybox_geometry(
        self,
        skybox: SkyDome,
        radius: float = 1.0,
        segments: int = 32,
        rings: int = 16,
    ) -> List[Mesh]:
        """Generate skybox dome geometry with proper UV mapping"""
        meshes = []

        if not skybox.upper_sky_texture and not skybox.lower_cloud_texture:
            return meshes

        # Generate hemisphere for standard zones, full sphere for special zones like Plane of Sky
        is_full_sphere = "plane" in skybox.name.lower() or "po" in skybox.name.lower()

        # Generate upper sky layer (main sky dome)
        if skybox.upper_sky_texture and skybox.upper_sky_texture in self.sky_files:
            upper_mesh = self._generate_dome_mesh(
                skybox.upper_sky_texture,
                radius * 0.95,  # Slightly smaller to be behind clouds
                segments,
                rings,
                is_full_sphere=is_full_sphere,
                layer_name="sky_upper",
            )
            if upper_mesh:
                meshes.append(upper_mesh)

        # Generate lower cloud layer (transparent clouds)
        if skybox.lower_cloud_texture and skybox.lower_cloud_texture in self.sky_files:
            cloud_mesh = self._generate_dome_mesh(
                skybox.lower_cloud_texture,
                radius,  # Full radius for clouds
                segments,
                rings,
                is_full_sphere=is_full_sphere,
                layer_name="sky_clouds",
                is_transparent=True,
            )
            if cloud_mesh:
                meshes.append(cloud_mesh)

        # Generate celestial objects (sun, moon, etc.)
        celestial_objects = []
        if skybox.sun_texture:
            celestial_objects.append(
                ("sun", skybox.sun_texture, (0.8, 0.6, 0))
            )  # Sun position
        if skybox.moon_texture:
            celestial_objects.append(
                ("moon", skybox.moon_texture, (-0.8, 0.3, 0))
            )  # Moon position

        for obj_name, texture_name, position in celestial_objects:
            if texture_name in self.sky_files:
                celestial_mesh = self._generate_celestial_object(
                    texture_name, position, radius * 0.9, obj_name
                )
                if celestial_mesh:
                    meshes.append(celestial_mesh)

        return meshes

    def _generate_dome_mesh(
        self,
        texture_name: str,
        radius: float,
        segments: int,
        rings: int,
        is_full_sphere: bool = False,
        layer_name: str = "sky",
        is_transparent: bool = False,
    ) -> Optional[Mesh]:
        """Generate a dome/sphere mesh with proper UV mapping"""
        try:
            vertices = []
            normals = []
            texcoords = []
            polygons = []

            # Generate vertices
            if is_full_sphere:
                ring_count = rings * 2  # Full sphere needs more rings
                ring_start = 0
            else:
                ring_count = rings  # Hemisphere uses all rings from top to horizon
                ring_start = 0

            for ring in range(ring_start, ring_count):
                # Calculate latitude angle (from top to bottom for proper hemisphere)
                if not is_full_sphere:
                    # Hemisphere: 0 (top) to π/2 (horizon)
                    lat_angle = math.pi * 0.5 * ring / (rings - 1)
                else:
                    # Full sphere: 0 (top) to π (bottom)
                    lat_angle = math.pi * ring / (ring_count - 1)

                # Standard spherical coordinates with Y-up (Three.js standard)
                y = radius * math.cos(
                    lat_angle
                )  # Y goes from +radius (top) to 0 (horizon) or -radius (bottom)
                ring_radius = radius * math.sin(
                    lat_angle
                )  # Ring gets larger toward horizon

                for segment in range(segments + 1):
                    # Calculate longitude angle
                    lon_angle = 2.0 * math.pi * segment / segments

                    # Standard Y-up coordinate system for Three.js
                    x = ring_radius * math.cos(lon_angle)
                    z = ring_radius * math.sin(lon_angle)

                    # Vertex position
                    vertices.append((x, y, z))

                    # Normal (pointing inward for skybox)
                    normal_len = math.sqrt(x * x + y * y + z * z)
                    normals.append((-x / normal_len, -y / normal_len, -z / normal_len))

                    # UV coordinates - spherical mapping
                    u = segment / segments
                    v = ring / (ring_count - 1) if ring_count > 1 else 0
                    texcoords.append((u, v))

                    # Generate triangles
            total_rings = ring_count - ring_start
            for ring in range(total_rings - 1):
                for segment in range(segments):
                    # Current ring vertices
                    curr_ring_start = ring * (segments + 1)
                    next_ring_start = (ring + 1) * (segments + 1)

                    v0 = curr_ring_start + segment
                    v1 = curr_ring_start + segment + 1
                    v2 = next_ring_start + segment
                    v3 = next_ring_start + segment + 1

                    # Two triangles per quad (with proper winding for inward-facing)
                    polygons.append((v0, v2, v1))  # First triangle
                    polygons.append((v1, v2, v3))  # Second triangle

            # Create vertex buffer
            vertex_data = flatten(interleave(vertices, normals, texcoords))
            vertex_buffer = VertexBuffer(vertex_data, len(vertices))

            # Create material
            texture_data = self.sky_files[texture_name]
            material_flags = (
                0x2 if is_transparent else 0
            )  # FLAG_TRANSLUCENT if transparent
            material = Material(material_flags, [texture_data], 0)

            # Create mesh
            mesh = Mesh(material, vertex_buffer, polygons, collidable=False)
            mesh.name = layer_name

            return mesh

        except Exception as e:
            print(f"Error generating dome mesh for {texture_name}: {e}")
            return None

    def _generate_celestial_object(
        self,
        texture_name: str,
        position: Tuple[float, float, float],
        distance: float,
        obj_name: str,
    ) -> Optional[Mesh]:
        """Generate a celestial object (sun, moon, etc.) as a billboard"""
        try:
            # Normalize position and scale to distance
            pos_x, pos_y, pos_z = position
            length = math.sqrt(pos_x * pos_x + pos_y * pos_y + pos_z * pos_z)
            pos_x = (pos_x / length) * distance
            pos_y = (pos_y / length) * distance
            pos_z = (pos_z / length) * distance

            # Create billboard quad
            size = distance * 0.05  # Relative size

            vertices = [
                (pos_x - size, pos_y + size, pos_z),  # Top-left
                (pos_x + size, pos_y + size, pos_z),  # Top-right
                (pos_x - size, pos_y - size, pos_z),  # Bottom-left
                (pos_x + size, pos_y - size, pos_z),  # Bottom-right
            ]

            # Normals pointing toward center (camera)
            normals = [(-pos_x / distance, -pos_y / distance, -pos_z / distance)] * 4

            # UV coordinates
            texcoords = [(0, 0), (1, 0), (0, 1), (1, 1)]

            # Two triangles for the quad
            polygons = [(0, 2, 1), (1, 2, 3)]

            # Create vertex buffer
            vertex_data = flatten(interleave(vertices, normals, texcoords))
            vertex_buffer = VertexBuffer(vertex_data, len(vertices))

            # Create material with alpha blending
            texture_data = self.sky_files[texture_name]
            material = Material(0x2, [texture_data], 0)  # FLAG_TRANSLUCENT

            # Create mesh
            mesh = Mesh(material, vertex_buffer, polygons, collidable=False)
            mesh.name = f"celestial_{obj_name}"

            return mesh

        except Exception as e:
            print(f"Error generating celestial object {obj_name}: {e}")
            return None

    def get_zone_skybox(self, zone_name: str) -> Optional[SkyDome]:
        """Get the appropriate skybox for a specific zone"""
        if not self.sky_files:
            return None

        # Zone-specific sky mappings based on EverQuest lore and environment
        zone_sky_mapping = {
            # Normal outdoor zones
            "qeynos": "normal",
            "qeynos2": "normal",
            "qeytoqrg": "normal",
            "halas": "normal",
            "everfrost": "normal",
            "blackburrow": "normal",
            "kithicor": "normal",
            "rivervale": "normal",
            "misty": "normal",
            "nektulos": "normal",
            "lavastorm": "normal",
            "soldunga": "normal",
            "solusekseye": "normal",
            "najena": "normal",
            "unrest": "normal",
            "befallen": "normal",
            "northkarana": "normal",
            "southkarana": "normal",
            "eastkarana": "normal",
            "westkarana": "normal",
            "qcat": "normal",
            "commons": "normal",
            "ecommons": "normal",
            "nfreeport": "normal",
            "sfreeport": "normal",
            "efreeport": "normal",
            "wfreeport": "normal",
            "freportn": "normal",
            "freporte": "normal",
            "freportw": "normal",
            "freports": "normal",
            "butcher": "normal",
            "oot": "normal",
            "cauldron": "normal",
            "dalnir": "normal",
            "paw": "normal",
            "splitpaw": "normal",
            "rathemtn": "normal",
            "nektulos": "normal",
            "lakerathe": "normal",
            # Desert zones
            "nro": "desert",
            "sro": "desert",
            "oasis": "desert",
            "innothule": "desert",
            "feerrott": "desert",
            "cazicthule": "desert",
            "desert": "desert",
            "southdesert": "desert",
            "northdesert": "desert",
            "eastdesert": "desert",
            "westdesert": "desert",
            # Luclin zones (moon environment)
            "nexus": "luclin",
            "bazaar": "luclin",
            "shadowhaven": "luclin",
            "sharvahl": "luclin",
            "paludal": "luclin",
            "hollowshade": "luclin",
            "grimling": "luclin",
            "tengu": "luclin",
            "maiden": "luclin",
            "dawnshroud": "luclin",
            "scarlet": "luclin",
            "umbral": "luclin",
            "mons": "luclin",
            "netherbian": "luclin",
            "ssratemple": "luclin",
            "griegsend": "luclin",
            "vexthal": "luclin",
            # Plane zones (special elemental skies)
            "airplane": "plane",  # Plane of Sky
            "fearplane": "plane",  # Plane of Fear
            "hateplane": "plane",  # Plane of Hate
            "poknowledge": "plane",  # Plane of Knowledge
            "potranquility": "plane",  # Plane of Tranquility
            "ponightmare": "plane",  # Plane of Nightmare
            "podisease": "plane",  # Plane of Disease
            "pojustice": "plane",  # Plane of Justice
            "powar": "plane",  # Plane of War
            "potorment": "plane",  # Plane of Torment
            "postorms": "plane",  # Plane of Storms
            "pofire": "plane",  # Plane of Fire
            "powater": "plane",  # Plane of Water
            "poeartha": "plane",  # Plane of Earth A
            "poearthb": "plane",  # Plane of Earth B
            "poair": "plane",  # Plane of Air
        }

        # Determine sky type for zone
        sky_type = zone_sky_mapping.get(zone_name.lower(), "normal")

        # Create skybox based on type
        skybox = SkyDome(f"{zone_name}_{sky_type}")

        if sky_type == "normal":
            skybox.upper_sky_texture = "normalsky.bmp"
            skybox.lower_cloud_texture = "normalcloud.bmp"
        elif sky_type == "desert":
            skybox.upper_sky_texture = "desertsky.bmp"
            skybox.lower_cloud_texture = "desertcloud.bmp"
        elif sky_type == "luclin":
            skybox.upper_sky_texture = "luclinsky1.bmp"
            skybox.lower_cloud_texture = "luclincloud1.bmp"
        elif sky_type == "plane":
            # Use different plane skies based on zone
            if "air" in zone_name.lower() or "sky" in zone_name.lower():
                skybox.upper_sky_texture = (
                    "poairsky1.tga"
                    if "poairsky1.tga" in self.sky_files
                    else "normalsky.bmp"
                )
                skybox.lower_cloud_texture = (
                    "powarclouds1.tga"
                    if "powarclouds1.tga" in self.sky_files
                    else "fluffycloud.bmp"
                )
                skybox.dome_type = "sphere"  # Full sphere for Plane of Sky
            elif "fire" in zone_name.lower():
                skybox.upper_sky_texture = (
                    "pofiresky1.tga"
                    if "pofiresky1.tga" in self.sky_files
                    else "redsky.bmp"
                )
                skybox.lower_cloud_texture = "redcloud.bmp"
            elif "storm" in zone_name.lower():
                skybox.upper_sky_texture = (
                    "postormsky1a.tga"
                    if "postormsky1a.tga" in self.sky_files
                    else "thegreysky.bmp"
                )
                skybox.lower_cloud_texture = (
                    "postormsky2.tga"
                    if "postormsky2.tga" in self.sky_files
                    else "thegreyclouds.bmp"
                )
            elif "tranq" in zone_name.lower():
                skybox.upper_sky_texture = (
                    "potranqsky1.tga"
                    if "potranqsky1.tga" in self.sky_files
                    else "normalsky.bmp"
                )
                skybox.lower_cloud_texture = (
                    "potranqsky2.tga"
                    if "potranqsky2.tga" in self.sky_files
                    else "cottonysky.bmp"
                )
            elif "war" in zone_name.lower():
                skybox.upper_sky_texture = (
                    "powarsky1.tga"
                    if "powarsky1.tga" in self.sky_files
                    else "redsky.bmp"
                )
                skybox.lower_cloud_texture = (
                    "powarclouds1.tga"
                    if "powarclouds1.tga" in self.sky_files
                    else "redcloud.bmp"
                )
            else:
                # Default plane sky
                skybox.upper_sky_texture = "normalsky.bmp"
                skybox.lower_cloud_texture = "cottonysky.bmp"

        # Add celestial objects to most outdoor zones
        if sky_type in ["normal", "desert", "luclin"]:
            skybox.sun_texture = "sun.bmp"
            skybox.moon_texture = "moon.bmp"
            # Add Saturn for Luclin zones (you can see it from the moon)
            if sky_type == "luclin":
                skybox.celestial_textures.append("saturn.bmp")

        # Validate that textures exist
        if skybox.upper_sky_texture and skybox.upper_sky_texture not in self.sky_files:
            print(
                f"Warning: Sky texture {skybox.upper_sky_texture} not found, using fallback"
            )
            skybox.upper_sky_texture = (
                "normalsky.bmp" if "normalsky.bmp" in self.sky_files else None
            )

        if (
            skybox.lower_cloud_texture
            and skybox.lower_cloud_texture not in self.sky_files
        ):
            print(
                f"Warning: Cloud texture {skybox.lower_cloud_texture} not found, using fallback"
            )
            skybox.lower_cloud_texture = (
                "normalcloud.bmp" if "normalcloud.bmp" in self.sky_files else None
            )

        return skybox
