from pprint import pprint
from math import *
import struct

# from pyrr import Matrix44, Quaternion, Vector3, Vector4
from buffer import Buffer
from utility import *
from zonefile import *
from charfile import *


class FragRef(object):
    def __init__(self, wld, id=None, name=None, value=None):
        self.wld = wld
        self.id = id
        self.name = name
        self.value = value

    def resolve(self):
        if self.value is not None:
            pass
        elif self.id is not None:
            self.value = self.wld.frags[self.id]
            if not self.wld.baked:
                self.value = self.value[3]
        elif self.name is not None:
            self.value = self.wld.names[self.name]
            if not self.wld.baked:
                self.value = self.value[3]
        if isinstance(self.value, FragRef):
            self.value = self.value.resolve()
        return self.value

    def __getitem__(self, index):
        return self.resolve()[index]

    def __len__(self):
        return len(self.resolve())

    def __repr__(self):
        if self.value is not None:
            if self.id is not None:
                return "FragRef(id=%r, value=%r)" % (self.id, self.value)
            else:
                return "FragRef(name=%r, value=%r)" % (self.name, self.value)
        elif self.id is not None:
            return "FragRef(id=%r)" % (self.id,)
        elif self.name is not None:
            return "FragRef(name=%r)" % (self.name,)


fragHandlers = {}


def fragment(type):
    def sub(f):
        fragHandlers[type] = f
        return f

    return sub


class Wld(object):
    def __init__(self, data, s3d):
        self.b = b = Buffer(data)
        self.s3d = s3d
        self.texture_warnings = {}

        assert b.uint() == 0x54503D02
        self.old = b.uint() == 0x00015500
        fragCount = b.uint()
        b += 8
        hashlen = b.uint()
        b += 4
        self.stringTable = self.decodeString(b.read(hashlen))

        self.baked = False
        self.frags = {}
        self.names = {}
        self.byType = {}
        for i in range(fragCount):
            size = b.uint()
            type = b.uint()
            nameoff = b.int()
            name = self.getString(-nameoff) if nameoff != 0x1000000 else None
            epos = b.pos + size - 4

            frag = fragHandlers[type](self) if type in fragHandlers else None
            if isinstance(frag, dict):
                frag["_name"] = name
            frag = (i, name, type, frag)
            self.frags[i] = frag
            if name != "" or type == 0x05:
                self.names[name] = frag
            if type not in self.byType:
                self.byType[type] = []
            self.byType[type].append(frag)

            b.pos = epos

        self.byType = {k: [] for k in self.byType}
        nfrags = {}
        nnames = {}
        for i, name, type, frag in self.frags.values():
            nfrags[i] = nnames[name] = frag
            self.byType[type].append(frag)
        self.frags = nfrags
        self.names = nnames
        self.baked = True

    def convertZone(self, zone):
        # Debug: Print fragment types found in this zone
        print(f"Fragment types in zone: {sorted(self.byType.keys())}")

        # Debug: Print any Fragment 2A (ambient) data
        if 0x2A in self.byType:
            print(f"Found {len(self.byType[0x2A])} Fragment 2A (ambient) entries")

        for meshfrag in self.byType[0x36]:
            vbuf = VertexBuffer(
                flatten(
                    interleave(
                        meshfrag["vertices"], meshfrag["normals"], meshfrag["texcoords"]
                    )
                ),
                len(meshfrag["vertices"]),
            )

            off = 0
            for count, index in meshfrag["polytex"]:
                if index >= len(meshfrag["textures"]):
                    key = f"convertZone_idx{index}_avail{len(meshfrag['textures'])}"
                    self.texture_warnings[key] = self.texture_warnings.get(key, 0) + 1

                    # Instead of skipping, create a fallback material
                    # Use index modulo available textures to get a valid texture
                    if len(meshfrag["textures"]) > 0:
                        fallback_index = index % len(meshfrag["textures"])
                        texflags, mtex = meshfrag["textures"][fallback_index]
                        if mtex.value is not None:
                            mtex = mtex.value.value
                            texnames = mtex["textures"]
                            # Debug: Look for sky-related textures
                            for texname in texnames:
                                if any(
                                    sky_word in texname[0].lower()
                                    for sky_word in ["sky", "cloud", "dome", "ambient"]
                                ):
                                    print(f"Found potential sky texture: {texname[0]}")
                            material = Material(
                                texflags,
                                [self.s3d[texname[0].lower()] for texname in texnames],
                                mtex["params"],
                            )
                            collidablePolys = [
                                x for c, x in meshfrag["polys"][off : off + count] if c
                            ]
                            noncollidablePolys = [
                                x
                                for c, x in meshfrag["polys"][off : off + count]
                                if not c
                            ]
                            if len(collidablePolys):
                                mesh = Mesh(
                                    material, vbuf, collidablePolys, collidable=True
                                )
                                zone.zoneobj.addMesh(mesh)
                            if len(noncollidablePolys):
                                mesh = Mesh(
                                    material, vbuf, noncollidablePolys, collidable=False
                                )
                                zone.zoneobj.addMesh(mesh)

                    off += count
                    continue

                texflags, mtex = meshfrag["textures"][index]
                if mtex.value is None:
                    off += count
                    continue
                mtex = mtex.value.value
                texnames = mtex["textures"]
                # Debug: Look for sky-related textures
                for texname in texnames:
                    if any(
                        sky_word in texname[0].lower()
                        for sky_word in ["sky", "cloud", "dome", "ambient"]
                    ):
                        print(f"Found potential sky texture: {texname[0]}")
                material = Material(
                    texflags,
                    [self.s3d[texname[0].lower()] for texname in texnames],
                    mtex["params"],
                )
                collidablePolys = [
                    x for c, x in meshfrag["polys"][off : off + count] if c
                ]
                noncollidablePolys = [
                    x for c, x in meshfrag["polys"][off : off + count] if not c
                ]
                if len(collidablePolys):
                    mesh = Mesh(material, vbuf, collidablePolys, collidable=True)
                    zone.zoneobj.addMesh(mesh)
                if len(noncollidablePolys):
                    mesh = Mesh(material, vbuf, noncollidablePolys, collidable=False)
                    zone.zoneobj.addMesh(mesh)
                off += count

    def convertObjects(self, zone):
        if 0x36 in self.byType:
            for meshfrag in self.byType[0x36]:
                obj_name = meshfrag["_name"].replace("_DMSPRITEDEF", "")
                obj = zone.addObject(obj_name)
                vbuf = VertexBuffer(
                    flatten(
                        interleave(
                            meshfrag["vertices"],
                            meshfrag["normals"],
                            meshfrag["texcoords"],
                        )
                    ),
                    len(meshfrag["vertices"]),
                )

                off = 0
                for count, index in meshfrag["polytex"]:
                    if index >= len(meshfrag["textures"]):
                        key = f"convertObjects_idx{index}_avail{len(meshfrag['textures'])}"
                        self.texture_warnings[key] = (
                            self.texture_warnings.get(key, 0) + 1
                        )
                        off += count
                        continue

                    # Debug texture access issue
                    try:
                        texture_item = meshfrag["textures"][index]
                        # Check if this is a tuple (texflags, mtex) or a single FragRef
                        if isinstance(texture_item, tuple) and len(texture_item) == 2:
                            texflags, mtex = texture_item
                        else:
                            # This is a direct texture bitmap info fragment, wrap it
                            texflags = 0  # Default flags
                            mtex = texture_item

                    except (KeyError, IndexError) as e:
                        # Skip problematic texture - continue silently
                        off += count
                        continue

                    # Handle different texture data formats
                    if isinstance(mtex, dict):
                        # Dict format: {'textures': [FragRef(...)], 'params': 0, '_name': '...'}
                        texnames = mtex["textures"]
                        params = mtex["params"]
                    elif isinstance(mtex, list):
                        # List format: ['ARMORSIGN.BMP'] - direct texture names
                        texnames = [
                            (name,) for name in mtex
                        ]  # Convert to expected tuple format
                        params = 0  # Default params for list format
                    elif hasattr(mtex, "value"):
                        # FragRef format: resolve it further
                        resolved_mtex = mtex.value
                        if isinstance(resolved_mtex, dict):
                            texnames = resolved_mtex["textures"]
                            params = resolved_mtex["params"]
                        elif (
                            isinstance(resolved_mtex, tuple) and len(resolved_mtex) == 2
                        ):
                            # Handle tuple format: (flags, fragref)
                            texflags, inner_fragref = resolved_mtex

                            # Resolve the inner FragRef
                            if hasattr(inner_fragref, "value"):
                                inner_resolved = inner_fragref.value

                                if isinstance(inner_resolved, dict):
                                    texnames = inner_resolved["textures"]
                                    params = inner_resolved["params"]
                                elif hasattr(inner_resolved, "value"):
                                    # Another level of FragRef nesting
                                    deep_resolved = inner_resolved.value

                                    if isinstance(deep_resolved, dict):
                                        texnames = deep_resolved["textures"]
                                        params = deep_resolved["params"]
                                    else:
                                        off += count
                                        continue
                                else:
                                    off += count
                                    continue
                            else:
                                off += count
                                continue
                        else:
                            # Skip unexpected texture format
                            off += count
                            continue
                    else:
                        # Skip unexpected texture format
                        off += count
                        continue

                    material = Material(
                        texflags,
                        [self.s3d[texname[0].lower()] for texname in texnames],
                        params,
                    )
                    collidablePolys = [
                        x for c, x in meshfrag["polys"][off : off + count] if c
                    ]
                    noncollidablePolys = [
                        x for c, x in meshfrag["polys"][off : off + count] if not c
                    ]
                    if len(collidablePolys):
                        mesh = Mesh(material, vbuf, collidablePolys, collidable=True)
                        obj.addMesh(mesh)
                    if len(noncollidablePolys):
                        mesh = Mesh(
                            material, vbuf, noncollidablePolys, collidable=False
                        )
                        obj.addMesh(mesh)
                    off += count
        if 0x15 in self.byType:
            for objfrag in self.byType[0x15]:
                objname = self.getString(-objfrag["nameoff"]).replace("_ACTORDEF", "")
                zone.addPlaceable(
                    objname, objfrag["position"], objfrag["rotation"], objfrag["scale"]
                )

    def convertLights(self, zone):
        for light in self.byType[0x28]:
            light["light"] = light["light"].resolve()
            zone.addLight(
                light["position"],
                light["radius"],
                light["light"]["attenuation"],
                light["light"]["color"],
                light["flags"],
            )

    def convertCharacters(self, zip):
        parents = {}

        def buildAniTree(prefix, idx, parent=-1):
            parents[idx] = parent
            track = skeleton["tracks"][idx]
            piecetrack = track["piecetrack"]
            if prefix != "" and (prefix + piecetrack["_name"]) in self.names:
                piecetrack = self.names[prefix + piecetrack["_name"]]
            return dict(
                bone=idx,
                frames=piecetrack["track"]["frames"],
                children=[buildAniTree(prefix, x, idx) for x in track["nextpieces"]],
            )

        def flattenTree(tree):
            def qm(x):
                return [x[0], x[1], x[2], -x[3]]

            out = {}
            out[tree["bone"]] = flatten(
                [(x["position"], qm(x["rotation"])) for x in tree["frames"]]
            )
            list(map(out.update, map(flattenTree, tree["children"])))
            return out

        for modelref in self.byType[0x14]:
            charfile = Charfile(modelref["_name"])
            assert len(modelref["skeleton"]) == 1
            skeleton = modelref["skeleton"][0]
            roottrackname = skeleton["tracks"][0]["piecetrack"]["_name"]
            prefixes = [""]
            for x in self.byType[0x13]:
                name = x["_name"]
                if name != roottrackname and name.endswith(roottrackname):
                    prefixes.append(name[: -len(roottrackname)])

            aniTrees = {}
            for prefix in prefixes:
                aniTrees[prefix] = buildAniTree(prefix, 0)

            for k, v in parents.items():
                assert k > v
                charfile.addBoneParent(k, v)

            meshes = skeleton["meshes"]
            for mesh in meshes:
                off = 0
                for count, index in mesh["polytex"]:
                    if index >= len(mesh["textures"]):
                        key = (
                            f"convertCharacters_idx{index}_avail{len(mesh['textures'])}"
                        )
                        self.texture_warnings[key] = (
                            self.texture_warnings.get(key, 0) + 1
                        )
                        off += count
                        continue
                    texflags, mtex = mesh["textures"][index]
                    mtex = mtex.value.value["textures"]
                    texnames = [x[0] for x in mtex]
                    material = Material(
                        texflags, [self.s3d[texname.lower()] for texname in texnames]
                    )
                    outverts = mesh["vertices"]
                    outnorms = mesh["normals"]
                    outtc = mesh["texcoords"]
                    outpolys = [x for _, x in mesh["polys"][off : off + count]]
                    outbones = []
                    for bc, bi in mesh["bonevertices"]:
                        outbones += [(bi,)] * bc
                    rmeshes = Mesh(
                        material,
                        VertexBuffer(
                            flatten(interleave(outverts, outnorms, outtc, outbones)),
                            len(outverts),
                        ),
                        outpolys,
                    ).optimize()
                    list(map(charfile.addMesh, rmeshes))
                    off += count
            for name, tree in aniTrees.items():
                boneframes = flattenTree(tree)
                assert len(boneframes) - 1 == sorted(boneframes)[-1]
                boneframes = [
                    v for k, v in sorted(boneframes.items(), key=lambda x: x[0])
                ]
                charfile.addAnimation(name, boneframes)
            charfile.out(zip)

    def getString(self, i):
        return self.stringTable[i:].split("\0", 1)[0]

    def print_texture_warnings(self):
        """Print a summary of texture index warnings instead of individual messages"""
        if not self.texture_warnings:
            return

        total_warnings = sum(self.texture_warnings.values())
        print(f"Texture index warnings: {total_warnings} instances")

        # Group by function
        by_function = {}
        for key, count in self.texture_warnings.items():
            func = key.split("_")[0]
            if func not in by_function:
                by_function[func] = 0
            by_function[func] += count

        for func, count in by_function.items():
            print(f"  {func}: {count} warnings")

    xorkey = 0x95, 0x3A, 0xC5, 0x2A, 0x95, 0x7A, 0x95, 0x6A

    def decodeString(self, s):
        if isinstance(s, bytes):
            return "".join(
                chr(x ^ Wld.xorkey[i % len(Wld.xorkey)]) for i, x in enumerate(s)
            )
        else:
            return "".join(
                chr(ord(x) ^ Wld.xorkey[i % len(Wld.xorkey)]) for i, x in enumerate(s)
            )

    def getFrag(self, ref):
        if ref > 0:
            ref -= 1
            if ref in self.frags:
                return FragRef(self, id=ref, value=self.frags[ref][3])
            return FragRef(self, id=ref)
        name = self.getString(-ref)
        if name in self.names:
            return FragRef(self, name=name, value=self.names[name][3])
        return FragRef(self, name=name)

    @fragment(0x03)
    def frag_texname(self):
        size = self.b.uint() + 1
        return [
            self.decodeString(self.b.read(self.b.ushort()))[:-1] for i in range(size)
        ]

    @fragment(0x04)
    def frag_texbitinfo(self):
        flags = self.b.uint()
        size = self.b.uint()
        params = 0
        if flags & (1 << 2):
            self.b.uint()
        if flags & (1 << 3):
            params = self.b.uint()
        return dict(textures=list(map(self.getFrag, self.b.int(size))), params=params)

    @fragment(0x05)
    def frag_texunk(self):
        return self.getFrag(self.b.int())

    @fragment(0x10)
    def frag_skeltrackset(self):
        flags = self.b.uint()
        trackcount = self.b.uint()
        frag1ref = self.getFrag(self.b.int())
        params1 = self.b.uint(3) if flags & 1 else None
        params2 = self.b.float() if flags & 2 else None

        tracks = []
        allmeshes = set()
        for i in range(trackcount):
            track = {}
            track["name"] = self.getString(-self.b.int())
            track["flags"] = self.b.uint()
            track["piecetrack"] = self.getFrag(self.b.int())
            allmeshes.add(self.b.int())
            track["nextpieces"] = self.b.int(self.b.uint())
            tracks.append(track)

        if flags & 0x200:
            meshes = list(map(self.getFrag, self.b.int(self.b.uint())))
        else:
            meshes = [self.getFrag(x) for x in allmeshes if x != 0]

        # print('digraph bones {')
        # for i in range(trackcount):
        #     print '_%i [label="%s"];' % (i, tracks[i]['name'])
        # for i, track in enumerate(tracks):
        #     for n in track['nextpieces']:
        #         print '_%i -> _%i;' % (i, n)
        # print('}')

        return dict(meshes=meshes, tracks=tracks)

    @fragment(0x11)
    def frag_skeltracksetref(self):
        return self.getFrag(self.b.uint())

    @fragment(0x12)
    def frag_skelpiecetrack(self):
        flags = self.b.uint()
        large = bool(flags & 8)

        framecount = self.b.uint()
        frames = []
        for i in range(framecount):
            rotw, rotx, roty, rotz = map(float, self.b.short(4))
            shiftx, shifty, shiftz, shiftden = map(float, self.b.short(4))

            rotx, roty, rotz, rotw = (
                (rotx / 16384.0, roty / 16384.0, rotz / 16384.0, rotw / 16384.0)
                if rotw != 0
                else (0, 0, 0, 1)
            )
            shiftx, shifty, shiftz = (
                (shiftx / shiftden, shifty / shiftden, shiftz / shiftden)
                if shiftden != 0
                else (0, 0, 0)
            )
            frames.append(
                dict(
                    position=(shiftx, shifty, shiftz),
                    rotation=(-rotx, -roty, -rotz, rotw),
                )
            )

        return dict(frames=frames)

    @fragment(0x13)
    def frag_skelpiecetrackref(self):
        skelpiecetrack = self.getFrag(self.b.uint())
        flags = self.b.uint()
        unk = self.b.uint() if flags & 1 else None
        return {"track": skelpiecetrack}

    @fragment(0x14)
    def frag_modelref(self):
        flags = self.b.uint()
        frag1 = self.b.uint()
        size1, size2 = self.b.uint(2)
        frag2 = self.b.uint()
        if flags & 1:
            params1 = self.b.uint()
        if flags & 2:
            params2 = self.b.uint()

        for i in range(size1):
            e1size = self.b.uint()
            e1data = [(self.b.uint(), self.b.float()) for i in range(e1size)]

        frags3 = self.b.uint(size2)
        name3 = self.decodeString(self.b.read(self.b.uint()))

        return {"skeleton": list(map(self.getFrag, frags3))}

    @fragment(0x15)
    def frag_objloc(self):
        sref = self.b.int()
        flags = self.b.uint()
        frag1_unk = self.b.uint()
        pos = self.b.float(3)
        rot = self.b.float(3)
        # rot = (rot[2], rot[1], rot[0])
        rot = (
            rot[2] / 512.0 * 360.0 * pi / 180.0,
            rot[1] / 512.0 * 360.0 * pi / 180.0,
            rot[0] / 512.0 * 360.0 * pi / 180.0,
        )
        scale = self.b.float(3)
        scale = (scale[2], scale[2], scale[2]) if scale[2] > 0.0001 else (1, 1, 1)
        frag2_unk = self.b.uint()
        params2 = self.b.uint()

        return dict(position=pos, rotation=rot, scale=scale, nameoff=sref)

    @fragment(0x1B)
    def frag_light_source(self):
        flags = self.b.uint()
        params2 = self.b.uint()
        attenuation = 200.0
        if flags & (1 << 4):
            if flags & (1 << 3):
                attenuation = self.b.uint()
            unk = self.b.float()
            color = self.b.float(3)
        else:
            params3a = self.b.float()
            color = (params3a, params3a, params3a)
        return dict(attenuation=attenuation, color=color)

    @fragment(0x1C)
    def frag_light_sourceref(self):
        return self.getFrag(self.b.int())

    @fragment(0x28)
    def frag_light_info(self):
        lref = self.getFrag(self.b.int())
        flags = self.b.uint()
        pos = self.b.float(3)
        radius = self.b.float()

        return dict(light=lref, flags=flags, position=pos, radius=radius)

    @fragment(0x2A)
    def frag_ambient(self):
        lref = self.getFrag(self.b.int())
        flags = self.b.uint()
        region_count = self.b.uint()
        regions = self.b.uint(region_count)

        print(
            f"Fragment 2A (Ambient): light_ref={lref}, flags=0x{flags:X}, region_count={region_count}, regions={regions}"
        )

        # Return the data for potential future use
        return dict(light_ref=lref, flags=flags, regions=regions)

    @fragment(0x2D)
    def frag_meshref(self):
        return self.getFrag(self.b.int())

    @fragment(0x30)
    def frag_texref(self):
        pairflags = self.b.uint()
        flags = self.b.uint()
        self.b += 12
        if (pairflags & 2) == 2:
            self.b += 8
        saneflags = 0
        if flags == 0:
            saneflags = FLAG_TRANSPARENT
        if (flags & (2 | 8 | 16)) != 0:
            saneflags |= FLAG_MASKED
        if (flags & (4 | 8)) != 0:
            saneflags |= FLAG_TRANSLUCENT

        if flags & 0xFFFF == 0x14:  # HACK: Tiger head in halas
            saneflags = 0

        texbitinfo_ref = self.getFrag(self.b.int())
        temp = saneflags, texbitinfo_ref
        return temp

    @fragment(0x31)
    def frag_texlist(self):
        # Texture list format: [always_zero][count][texture_ref_1][texture_ref_2]...[texture_ref_n]
        zero_value = self.b.uint()  # This is always 0
        count = self.b.uint()  # Number of texture references

        result = []
        for i in range(count):
            texture_ref_id = self.b.uint()
            if texture_ref_id > 0:
                result.append(self.getFrag(texture_ref_id))

        return result

    @fragment(0x36)
    def frag_mesh(self):
        out = {}

        flags, tlistref, aniref = self.b.uint(3)
        out["textures"] = self.getFrag(tlistref)

        self.b += 8
        center = self.b.vec3()
        self.b += 12
        maxdist = self.b.float()
        min, max = self.b.vec3(2)
        vertcount, texcoordcount, normalcount, colorcount = self.b.ushort(4)
        polycount, vertpiececount, polytexcount, verttexcount = self.b.ushort(4)
        size9 = self.b.ushort()
        scale = float(1 << self.b.ushort())

        out["vertices"] = [
            (
                self.b.short() / scale + center[0],
                self.b.short() / scale + center[1],
                self.b.short() / scale + center[2],
            )
            for i in range(vertcount)
        ]
        if texcoordcount == 0:
            out["texcoords"] = [(0, 0)] * vertcount
        else:
            out["texcoords"] = [
                (
                    (self.b.short() / 256.0, self.b.short() / 256.0)
                    if self.old
                    else self.b.float(2)
                )
                for i in range(texcoordcount)
            ]
        out["normals"] = [
            (self.b.char() / 127.0, self.b.char() / 127.0, self.b.char() / 127.0)
            for i in range(normalcount)
        ]
        tcolors = self.b.uint(colorcount)
        if colorcount == 0:
            tcolors = [0] * vertcount
        assert len(tcolors) == vertcount
        out["colors"] = [
            [struct.unpack("<f", struct.pack("<I", x))[0]] for x in tcolors
        ]
        out["polys"] = [
            (self.b.ushort() != 0x0010, self.b.ushort(3)) for i in range(polycount)
        ]
        out["bonevertices"] = [self.b.ushort(2) for i in range(vertpiececount)]
        out["polytex"] = [self.b.ushort(2) for i in range(polytexcount)]

        return out
