#!/usr/bin/env python3
"""
Concise Texture Debug Script for OpenEQ Converter
Quick analysis of texture processing success rates
"""

import sys
from os.path import join
from collections import defaultdict, Counter
from glob import glob
from buffer import Buffer
from s3d import readS3D
from wld import Wld


class TextureAnalyzer:
    def __init__(self):
        self.stats = {
            "total_meshes": 0,
            "total_polytex_entries": 0,
            "successful_textures": 0,
            "failed_textures": 0,
            "texture_index_warnings": 0,
            "texture_lists_found": 0,
            "mesh_texture_counts": [],
            "max_texture_index": 0,
        }

    def analyze_mesh_textures(self, wld):
        """Analyze mesh texture usage patterns - concise version"""
        if 0x36 not in wld.byType:
            return

        for meshfrag in wld.byType[0x36]:
            textures = meshfrag.get("textures", [])
            polytex = meshfrag.get("polytex", [])

            self.stats["total_meshes"] += 1
            self.stats["mesh_texture_counts"].append(len(textures))

            for count, index in polytex:
                self.stats["total_polytex_entries"] += 1
                self.stats["max_texture_index"] = max(
                    self.stats["max_texture_index"], index
                )

                if index >= len(textures):
                    self.stats["texture_index_warnings"] += 1
                    self.stats["failed_textures"] += count
                else:
                    self.stats["successful_textures"] += count

    def analyze_texture_lists(self, wld):
        """Count texture lists"""
        if 0x31 in wld.byType:
            self.stats["texture_lists_found"] += len(wld.byType[0x31])

    def print_summary(self):
        """Print concise summary"""
        total_polys = self.stats["successful_textures"] + self.stats["failed_textures"]
        success_rate = (
            (self.stats["successful_textures"] / total_polys * 100)
            if total_polys > 0
            else 0
        )

        print(f"TEXTURE ANALYSIS SUMMARY")
        print(f"========================")
        print(f"Meshes: {self.stats['total_meshes']}")
        print(f"Polytex entries: {self.stats['total_polytex_entries']}")
        print(f"Total polygons: {total_polys}")
        print(f"Success rate: {success_rate:.1f}%")
        print(f"Index warnings: {self.stats['texture_index_warnings']}")
        print(f"Texture lists: {self.stats['texture_lists_found']}")
        print(f"Max texture index used: {self.stats['max_texture_index']}")

        if self.stats["mesh_texture_counts"]:
            avg_textures = sum(self.stats["mesh_texture_counts"]) / len(
                self.stats["mesh_texture_counts"]
            )
            print(f"Avg textures per mesh: {avg_textures:.1f}")

            # Show texture count distribution
            distribution = Counter(self.stats["mesh_texture_counts"])
            print(f"Texture counts: {dict(sorted(distribution.items()))}")


def analyze_zone(zone_name, eqdata_path):
    """Analyze a specific zone - concise version"""
    analyzer = TextureAnalyzer()

    try:
        # Load files
        objfiles = {}
        for fn in glob(join(eqdata_path, f"{zone_name}_obj*.s3d")):
            objfiles[fn.split("/")[-1][:-4]] = readS3D(open(fn, "rb"))

        zfiles = readS3D(open(join(eqdata_path, f"{zone_name}.s3d"), "rb"))

        # Analyze WLD files
        wld_files = []

        # Object files
        for obj_name, sf in objfiles.items():
            if f"{obj_name}.wld" in sf:
                wld = Wld(sf[f"{obj_name}.wld"], sf)
                wld_files.append(wld)

        # Zone files
        for wld_name in ["objects.wld", "lights.wld", f"{zone_name}.wld"]:
            if wld_name in zfiles:
                wld = Wld(zfiles[wld_name], zfiles)
                wld_files.append(wld)

        # Analyze all WLD files
        for wld in wld_files:
            analyzer.analyze_texture_lists(wld)
            analyzer.analyze_mesh_textures(wld)

        analyzer.print_summary()

    except Exception as e:
        print(f"Error: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 texture_debug.py <zone_name>")
        sys.exit(1)

    zone_name = sys.argv[1]

    # Read config
    try:
        with open("openeq.cfg", "r") as fp:
            configdata = fp.read()

        config = dict(
            [x.strip() for x in line.split("=", 1)]
            for line in [x.split("#", 1)[0] for x in configdata.split("\n")]
            if "=" in line
        )

        eqdata_path = config["eqdata"]
    except Exception as e:
        print(f"Config error: {e}")
        sys.exit(1)

    print(f"Analyzing {zone_name}...")
    analyze_zone(zone_name, eqdata_path)


if __name__ == "__main__":
    main()
