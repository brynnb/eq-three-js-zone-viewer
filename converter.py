from os.path import exists, join
import os

from glob import glob
from buffer import Buffer
from s3d import readS3D
from wld import Wld
from zon import readZon
from zonefile import Zone
from direct_gltf_export import export_zone_to_gltf
from sky import SkyProcessor


def s3dFallback(*filedicts):
    ndicts = []
    for files in filedicts:
        nfiles = {}
        ndicts.append(nfiles)
        for xfiles in filedicts:
            if xfiles is not files:
                nfiles.update(xfiles)
        nfiles.update(files)
    return ndicts


def eqPath(fn):
    return join(eqdata, fn).replace("\\", "/")


def ensure_output_dir():
    """Ensure the output directory exists"""
    if not os.path.exists("output"):
        os.makedirs("output")


def convertOld(name):
    """Convert old format EverQuest zone files directly to glTF"""
    zone = Zone()
    objfiles = {}
    for fn in glob(eqPath("%s_obj*.s3d" % name)):
        objfiles[fn.split("/")[-1][:-4]] = readS3D(open(fn, "rb"))

    zfiles = readS3D(open(eqPath("%s.s3d" % name), "rb"))
    flists = list(objfiles.values()) + [zfiles]
    flists = s3dFallback(*flists)
    for i, fn in enumerate(objfiles.keys()):
        objfiles[fn] = flists[i]
    zfiles = flists[-1]

    wld_instances = []
    for fn, sf in objfiles.items():
        wld_file_name = f"{fn}.wld"
        if wld_file_name in sf:
            wld_obj = Wld(sf[wld_file_name], sf)
            wld_obj.convertObjects(zone)
            wld_instances.append(wld_obj)

    objects_wld = Wld(zfiles["objects.wld"], zfiles)
    objects_wld.convertObjects(zone)
    wld_instances.append(objects_wld)

    lights_wld = Wld(zfiles["lights.wld"], zfiles)
    lights_wld.convertLights(zone)
    wld_instances.append(lights_wld)

    zone_wld = Wld(zfiles["%s.wld" % name], zfiles)
    zone_wld.convertZone(zone)
    wld_instances.append(zone_wld)

    # Process skybox data
    sky_processor = SkyProcessor(eqdata)
    if sky_processor.load_sky_data():
        skybox = sky_processor.get_zone_skybox(name)
        if skybox:
            print(f"Adding skybox: {skybox}")
            skybox_meshes = sky_processor.generate_skybox_geometry(skybox)
            if skybox_meshes:
                # Add skybox as a special object
                skybox_obj = zone.addObject("_SKYBOX_")
                for mesh in skybox_meshes:
                    skybox_obj.addMesh(mesh)
                print(f"Generated skybox with {len(skybox_meshes)} layers")
            else:
                print("Warning: No skybox geometry generated")
        else:
            print("Warning: No skybox configuration found for zone")
    else:
        print("Warning: Could not load sky data")

    # Print texture warning summary
    for wld in wld_instances:
        wld.print_texture_warnings()

    # Direct glTF export to output folder
    ensure_output_dir()
    output_path = join("output", f"{name}.glb")
    export_zone_to_gltf(zone, output_path)


def convertChr(name):
    """Character conversion - for now just inform that it's not supported in direct mode"""
    print("Character model conversion not yet implemented for direct glTF export.")
    print("This feature will be added in a future update.")


def convertNew(name):
    """Convert new format EverQuest zone files directly to glTF"""
    zone = Zone()
    zfiles = readS3D(open(eqPath("%s.eqg" % name), "rb"))

    if "%s.zon" % name in zfiles:
        readZon(zfiles["%s.zon" % name], zone, zfiles)
    else:
        readZon(open(eqPath("%s.zon" % name), "rb").read(), zone, zfiles)

    # Process skybox data
    sky_processor = SkyProcessor(eqdata)
    if sky_processor.load_sky_data():
        skybox = sky_processor.get_zone_skybox(name)
        if skybox:
            print(f"Adding skybox: {skybox}")
            skybox_meshes = sky_processor.generate_skybox_geometry(skybox)
            if skybox_meshes:
                # Add skybox as a special object
                skybox_obj = zone.addObject("_SKYBOX_")
                for mesh in skybox_meshes:
                    skybox_obj.addMesh(mesh)
                print(f"Generated skybox with {len(skybox_meshes)} layers")
            else:
                print("Warning: No skybox geometry generated")
        else:
            print("Warning: No skybox configuration found for zone")
    else:
        print("Warning: Could not load sky data")

    # Direct glTF export to output folder
    ensure_output_dir()
    output_path = join("output", f"{name}.glb")
    export_zone_to_gltf(zone, output_path)


def main(name):
    """Main conversion function - now only does direct glTF export"""
    global eqdata, config

    with open("openeq.cfg", "r") as fp:
        configdata = fp.read()

    config = dict(
        [x.strip() for x in line.split("=", 1)]
        for line in [x.split("#", 1)[0] for x in configdata.split("\n")]
        if "=" in line
    )

    eqdata = config["eqdata"]

    print(f"Converting {name} to glTF format...")

    if "_chr" in name:
        convertChr(name)
    elif exists(eqPath("%s.s3d" % name)):
        convertOld(name)
    elif exists(eqPath("%s.eqg" % name)):
        convertNew(name)
    else:
        print("Cannot find zone")
        return

    print(f"glTF conversion complete: output/{name}.glb")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 converter.py <zone_name>")
        print("Output: output/<zone_name>.glb")
        sys.exit(1)

    zone_name = sys.argv[1]
    main(zone_name)
