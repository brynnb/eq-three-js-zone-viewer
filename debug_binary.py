#!/usr/bin/env python3
"""
Debug script to analyze zone.oez binary format
"""

import struct
import zipfile
import sys


def debug_zone_binary(zip_path):
    """Debug the binary format of zone.oez"""

    with zipfile.ZipFile(zip_path, "r") as zip_file:
        zone_binary = zip_file.read("zone.oez")

    print(f"Total binary size: {len(zone_binary)} bytes")

    pos = 0

    # Read materials
    if pos + 4 <= len(zone_binary):
        num_materials = struct.unpack("<I", zone_binary[pos : pos + 4])[0]
        pos += 4
        print(f"\nMaterials: {num_materials}")

        for i in range(num_materials):
            if pos + 12 <= len(zone_binary):
                flags, param, num_filenames = struct.unpack(
                    "<III", zone_binary[pos : pos + 12]
                )
                pos += 12
                print(
                    f"  Material {i}: flags={flags}, param={param}, filenames={num_filenames}"
                )

                # Skip filenames with proper variable-length decoding
                for j in range(num_filenames):
                    strlen = 0
                    shift = 0
                    while pos < len(zone_binary):
                        byte = zone_binary[pos]
                        pos += 1
                        strlen |= (byte & 0x7F) << shift
                        if (byte & 0x80) == 0:
                            break
                        shift += 7

                    if strlen > 0 and pos + strlen <= len(zone_binary):
                        filename = zone_binary[pos : pos + strlen].decode("utf-8")
                        print(f"    Filename {j}: {filename}")
                        pos += strlen

    # Read objects
    if pos + 4 <= len(zone_binary):
        num_objects = struct.unpack("<I", zone_binary[pos : pos + 4])[0]
        pos += 4
        print(f"\nObjects: {num_objects}")

        for i in range(min(num_objects, 5)):  # Only debug first 5 objects
            if pos + 4 <= len(zone_binary):
                num_meshes = struct.unpack("<I", zone_binary[pos : pos + 4])[0]
                pos += 4
                print(f"\n  Object {i}: {num_meshes} meshes (pos={pos})")

                if num_meshes > 100000:  # Suspicious count
                    print(
                        f"    ERROR: Suspicious mesh count! Binary stream likely corrupted."
                    )
                    print(
                        f"    Binary data at position {pos-4}: {zone_binary[pos-4:pos+12].hex()}"
                    )
                    break

                for j in range(
                    min(num_meshes, 3)
                ):  # Only debug first 3 meshes per object
                    if pos + 16 <= len(zone_binary):
                        mat_id, collidable, num_verts, num_polygons = struct.unpack(
                            "<IIII", zone_binary[pos : pos + 16]
                        )
                        pos += 16
                        print(
                            f"    Mesh {j}: mat_id={mat_id}, collidable={collidable}, verts={num_verts}, polys={num_polygons}"
                        )

                        if num_verts > 100000 or num_polygons > 100000:
                            print(f"      ERROR: Suspicious vertex/polygon count!")
                            print(f"      Binary data: {zone_binary[pos-16:pos].hex()}")
                            return

                        # Calculate expected data sizes
                        vertex_data_size = (
                            num_verts * 9 * 4
                        )  # Assuming 9 floats per vertex
                        index_data_size = (
                            num_polygons * 3 * 4
                        )  # 3 indices per polygon, 4 bytes each

                        print(f"      Expected vertex data: {vertex_data_size} bytes")
                        print(f"      Expected index data: {index_data_size} bytes")

                        # Check if we have enough data
                        total_mesh_data = vertex_data_size + index_data_size
                        if pos + total_mesh_data > len(zone_binary):
                            print(
                                f"      ERROR: Not enough data! Need {total_mesh_data}, have {len(zone_binary) - pos}"
                            )
                            return

                        # Skip the vertex and index data for now
                        pos += total_mesh_data
                        print(f"      New position after mesh data: {pos}")
                    else:
                        print(f"    ERROR: Not enough data for mesh {j} header")
                        return

                if num_meshes > 3:
                    print(f"    ... (skipping remaining {num_meshes - 3} meshes)")
                    # Skip remaining meshes - this is where we might lose sync
                    for j in range(3, num_meshes):
                        if pos + 16 <= len(zone_binary):
                            mat_id, collidable, num_verts, num_polygons = struct.unpack(
                                "<IIII", zone_binary[pos : pos + 16]
                            )
                            pos += 16
                            vertex_data_size = num_verts * 9 * 4
                            index_data_size = num_polygons * 3 * 4
                            pos += vertex_data_size + index_data_size
                        else:
                            print(f"    ERROR: Lost sync while skipping mesh {j}")
                            return
            else:
                print(f"  ERROR: Not enough data for object {i}")
                return

    print(f"\nFinal position: {pos} / {len(zone_binary)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_binary.py <zone.zip>")
        sys.exit(1)

    debug_zone_binary(sys.argv[1])
