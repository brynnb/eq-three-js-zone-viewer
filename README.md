# EQ Three.js Zone Viewer

<img width="1350" alt="eqscreen" src="https://github.com/user-attachments/assets/eb366f12-39db-4b9f-90dc-ee168bf79b0c" />

A Python-based converter for extracting and converting classic EverQuest game assets into modern web-viewable formats, plus a simple web-based application using Three.js to navigate around the zones. Based on initial work in [OpenEQ Project](https://github.com/daeken/OpenEQ). I ultimately stopped progress on this project after finding the very new [eqrequiem](https://github.com/knervous/eqrequiem) project, which has done all the work here but better and to a much larger extent (which is very cool!).

## Overview

This converter processes original EverQuest game files and converts them into modern 3D formats. It handles complex proprietary game data including:

- **3D Zone Geometry** - Buildings, terrain, objects
- **Textures** - Environmental and object textures
- **Materials** - Surface properties and transparency
- **Character Models** - 3D models with animations (basic support)
- **Scene Structure** - Object placement and hierarchy

## File Format Support

### Input Formats (EverQuest Proprietary)

#### `.S3D` Files (Sony 3D Archive)

- **Purpose**: Container format for EverQuest assets
- **Structure**: Compressed archive containing multiple files
- **Contents**: WLD files, textures, models, animations
- **Compression**: Custom deflate-based compression
- **Directory**: Contains file table with CRC32 checksums

#### `.WLD` Files (World Definition)

- **Purpose**: 3D scene and model definitions
- **Structure**: Binary format with fragment-based architecture
- **Key Fragments**:
  - `0x03` - Texture references
  - `0x14` - Actor definitions (characters)
  - `0x15` - Object instances and placement
  - `0x28` - Light definitions
  - `0x31` - Texture lists
  - `0x36` - Mesh geometry data
- **Complexity**: Hierarchical references between fragments

#### `.TER` / `.MOD` Files (Terrain/Model Data)

- **Purpose**: Geometry data for newer EverQuest zones
- **Structure**: Binary format with material definitions
- **Contents**: Vertex data, polygon indices, material properties
- **Versions**: Multiple format versions supported

#### Texture Formats

- **BMP**: Standard bitmap images
- **DDS**: DirectDraw Surface (compressed textures)
- **Support**: Automatic format detection and conversion

### Output Formats

#### `.GLB` Files (glTF Binary)

For Three.js and web development:

- **Industry Standard**: Khronos Group glTF 2.0
- **Features**: PBR materials, embedded textures, scene hierarchy
- **Size**: ~80% smaller than original files
- **Compatibility**: All modern 3D engines and browsers

## Installation & Setup

### Prerequisites

- **Python 3.7+**
- **EverQuest Files** in accessible directory

### Configuration

1. **Clone Repository**:

   ```bash
   git clone https://github.com/your-username/eq-three-js-zone-viewer.git
   cd eq-three-js-zone-viewer
   ```

2. **Create Configuration** (`openeq.cfg`):

   ```ini
   [EverQuest]
   # Path to your EverQuest files
   eq_path = /Users/someuser/someeqinstallfolder

   [Converter]
   # Enable texture resampling for size optimization
   resample = true

   # Output format options
   include_collision = true
   optimize_meshes = true
   ```

3. **Verify File Structure**:
   ```
   someeqinstallfolder/
   ├── gfaydark.s3d          # Main zone file
   ├── gfaydark_obj.s3d      # Zone objects
   ├── gfaydark_chr.s3d      # Characters (optional)
   ├── objects.wld           # Global objects
   └── lights.wld            # Lighting data
   ```

## Usage

### Zone Conversion

```bash
# Convert EverQuest zone to glTF format
python3 converter.py gfaydark

# Output: output/gfaydark.glb (ready for Three.js/web)
```

### Character Model Conversion

```bash
# Character conversion (coming soon)
python3 converter.py gfaydark_chr

# Currently shows: "Character model conversion not yet implemented"
```

### Batch Conversion

```bash
# Convert multiple zones
for zone in gfaydark qeynos freeport; do
    python3 converter.py $zone
done

# All output goes to output/ folder
```

## Output Format

### glTF Binary (.glb)

The converter outputs industry-standard glTF 2.0 binary files optimized for web use:

- **Format**: Self-contained .glb files in `output/` folder
- **Size**: ~1MB for typical zones (80% smaller than original)
- **Speed**: Fast single-step conversion
- **Compatibility**: Works with Three.js, Blender, Unity, and all modern 3D engines
- **Features**: Embedded textures, materials, and geometry

### Output File Structure

```
output/
└── gfaydark.glb          # Single self-contained file
    ├── JSON scene data   # Embedded metadata
    ├── Binary mesh data  # Optimized geometry
    └── PNG textures      # Embedded and converted
```

## Three.js Integration

### Quick Start

```javascript
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const loader = new GLTFLoader();
loader.load("gfaydark.glb", function (gltf) {
  scene.add(gltf.scene);

  // Auto-fit camera
  const box = new THREE.Box3().setFromObject(gltf.scene);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());

  camera.position.set(center.x, center.y + size.y, center.z + size.z);
  camera.lookAt(center);
});
```

### Viewer Application

Use the included `three_js_viewer.html` for immediate viewing:

1. Open in web browser
2. Drag & drop `.glb` files
3. Interactive 3D exploration

**Controls**:

- **Orbit**: Left click + drag
- **Zoom**: Mouse wheel
- **Pan**: Right click + drag

## Technical Details

### EverQuest File Format Insights

#### S3D Archive Structure

```
File Header:
  - Directory offset (uint32)
  - Magic "PFS " (0x20534650)

Directory Section:
  - Chunk count (uint32)
  - Chunks array:
    - CRC32 checksum (uint32)
    - Data offset (uint32)
    - Compressed size (uint32)

Filename Directory:
  - Special chunk (CRC: 0x61580AC9)
  - Contains null-terminated filenames
  - Maps to chunk indices
```

#### WLD Fragment System

```
Fragment Header:
  - Size (uint32)
  - Type (uint32)
  - Name reference (uint32)

Fragment Types:
  0x03 - Texture Definition
  0x04 - Texture List Reference
  0x05 - Material Definition
  0x14 - Actor Definition (Character)
  0x15 - Object Instance
  0x28 - Light Definition
  0x31 - Texture List
  0x36 - Mesh Definition
```

#### Texture Index System Discovery

**Original Assumption**: `[count][ref1][ref2]...[refN]`
**Actual Format**: `[0][reference]` (single reference per list)

This discovery resolved major texture processing issues.

### Vertex Data Layout

```c
struct Vertex {
    float position[3];    // X, Y, Z coordinates
    float normal[3];      // Surface normal vector
    float texcoord[2];    // UV texture coordinates
    float bone_index;     // Skeletal animation (characters)
};
```

### Material Flag System

```c
// Material flags mapping
FLAG_NORMAL       = 0x00    // Standard opaque material
FLAG_TRANSPARENT  = 0x04    // Alpha blending
FLAG_ALPHA_MASK   = 0x02    // Alpha testing
FLAG_EMISSIVE     = 0x08    // Self-illuminated
FLAG_ANIMATED     = 0x10    // Texture animation
```

### Coordinate System Transformation

EverQuest uses a **Z-up coordinate system**, which differs from the modern industry standard used by glTF and most web technologies.

#### Coordinate System Differences

**EverQuest (Z-up)**:

- **X-axis**: Right
- **Y-axis**: Forward (into the screen)
- **Z-axis**: Up (vertical)

**glTF Standard (Y-up)**:

- **X-axis**: Right
- **Y-axis**: Up (vertical)
- **Z-axis**: Back (out of the screen)

This is similar to the difference between:

- **Z-up software**: 3ds Max, older CAD applications, some game engines
- **Y-up software**: Maya, Blender, Unity, most modern web frameworks

#### Conversion Process

The converter automatically handles this transformation during export:

**Position Transformation**:

```
EverQuest (x, y, z) → glTF (x, z, -y)
```

**Rotation Transformation**:

```
EverQuest (rot_x, rot_y, rot_z) → glTF (rot_x, rot_z, -rot_y)
```

**Normal Vector Transformation**:

```
EverQuest (nx, ny, nz) → glTF (nx, nz, -ny)
```

#### Impact on Output

- **Zone geometry** appears correctly oriented in all glTF viewers
- **Object placement** matches original EverQuest positioning
- **Prop rotations** (doors, furniture, etc.) are properly aligned
- **Camera movements** feel natural in Three.js applications

**Technical Note**: This transformation is applied at the vertex level during glTF generation, ensuring that the output files are fully compliant with the glTF 2.0 specification and work correctly in all standard 3D applications and web frameworks.

### Invisible Walls & Collision Detection

**Current Implementation**: Invisible zone boundary walls (FLAG_TRANSPARENT materials) are completely excluded from glTF export to prevent them from rendering as visible colored walls in viewers.

**Background**: EverQuest zones include invisible collision boundaries around their edges to prevent players from walking outside the playable area. These walls use `FLAG_TRANSPARENT` materials but still contain texture data, causing them to render as large colored barriers in 3D viewers.

**Current Solution**:

- Invisible walls are detected and separated in `ter.py` during terrain processing
- They are preserved in zone data with `collidable=True` for potential collision detection
- They are completely excluded from glTF export in `direct_gltf_export.py` to prevent visual rendering

**Future Considerations**:

- Game engines may need these collision boundaries for proper gameplay mechanics
- Consider adding a command-line option to include/exclude collision geometry
- May need to implement invisible collision-only materials in glTF (extensions or custom properties)
- Physics engines typically require explicit collision meshes separate from visual geometry

**Files Modified**:

- `converter/ter.py` - Separates invisible walls but keeps them collidable
- `converter/direct_gltf_export.py` - Excludes FLAG_TRANSPARENT materials from export

## EverQuest Sky System

### Architecture Overview

EverQuest uses a sophisticated **dedicated sky system** that is separate from zone geometry. Unlike modern games that use static skyboxes, EverQuest implemented a dynamic, multi-layered sky rendering system.

### Sky File Structure

**Sky assets are stored in separate files, NOT in zone WLD files:**

- `sky.s3d` - Contains sky textures and geometry data
- `sky.wld` - Contains sky fragment definitions and animations
- **Zone files do NOT contain skybox data** - this is why our current converter doesn't export sky elements

### Technical Implementation

#### Two-Layer Rendering System

1. **Upper Sky Layer** (Opaque)

   - Base sky color/gradient
   - Main atmospheric backdrop
   - Rendered first as background

2. **Lower Cloud Layer** (Transparent)
   - Cloud formations and weather effects
   - Alpha-blended over sky layer
   - Animated independently

#### Sky Objects

Rendered **between** the two layers:

- **Sun** - Animated position based on time of day
- **Moon** - Phases and position cycling
- **Planets** - Multiple celestial bodies
- **Stars** - Nighttime stellar backdrop

#### Geometry System

**Skydome Structure**:

- **Standard Zones**: Half oblate spheroid (dome shape)
- **Plane of Sky**: Full spheroid (complete sphere)
- **Texture Mapping**: Spherical UV coordinates

#### Animation System

**Multi-Speed Texture Panning**:

- Upper layer: Slow drift (base atmospheric movement)
- Lower layer: Faster movement (cloud drift)
- **Independent speeds** create realistic parallax effect
- **Seamless tiling** prevents visible texture boundaries

### Sky Variants

EverQuest includes **5 different sky configurations**:

1. **Clear Sky** - Minimal cloud cover, bright atmosphere
2. **Partly Cloudy** - Moderate cloud formations
3. **Overcast** - Heavy cloud cover, dimmer lighting
4. **Stormy** - Dark clouds, dramatic lighting
5. **Special** - Unique skies for specific zones (Plane of Sky, etc.)

### Current Converter Limitations

**Why skyboxes aren't currently exported:**

1. **Separate File System** - Sky data is in `sky.s3d`/`sky.wld`, not zone files
2. **Complex Animation** - Multi-layer texture panning system
3. **Time-of-Day Integration** - Sky appearance changes based on game time
4. **Celestial Object Rendering** - Sun/moon positioning calculations

### Implementation Roadmap

**To add proper EverQuest sky support:**

1. **Parse Sky Files**

   - Add `sky.s3d` and `sky.wld` parsing support
   - Extract sky texture layers and geometry

2. **Sky Fragment Support**

   - Implement sky-specific WLD fragment types
   - Parse animation and timing data

3. **glTF Sky Export**

   - Export skydome geometry as separate mesh
   - Embed sky textures with proper UV mapping
   - Add metadata for animation parameters

4. **Three.js Integration**
   - Implement multi-layer sky rendering
   - Add texture panning animations
   - Support celestial object positioning

### References

- **EQEmu Documentation** - Sky system implementation details
- **Original EverQuest Client** - Sky rendering pipeline
- **Reverse Engineering** - Community documentation of sky formats

**Note**: This represents one of the most sophisticated sky systems in classic MMORPGs, predating modern physically-based atmospheric rendering by many years.

## Status & Known Issues

### ✅ Fully Functional

- **Zone Conversion**: All major zones supported
- **Texture Processing**: PNG conversion working
- **Material System**: Transparency and properties preserved
- **Three.js Export**: Web-ready glTF generation
- **File Size**: Optimized output formats

### ⚠️ Known Limitations

#### Texture Index Warnings

Some polygons reference texture indices that don't exist:

```
Warning: Texture index 1 out of range (available: 1) in convertObjects
Warning: Texture index 10 out of range (available: 1) in convertZone
```

**Analysis**:

- Converter continues to function
- Textures are processed correctly
- Some polygons may use fallback materials
- Likely indicates complex multi-texture systems in EverQuest

**Impact**: Minimal - output is usable but may not be 100% accurate

#### Missing Features

- **Characters and Animations**: Not implemented
- **Lighting**: Lighting objects are placed but not rendering properly in three.js
- **Audio**: Not implemented

### Development Setup

```bash
# Create development environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Testing New Zones

1. Ensure EverQuest files are accessible
2. Run converter with debug output:
   ```bash
   python3 converter.py <zone_name> --debug
   ```
3. Check output for warnings and errors
4. Validate with Three.js viewer

### Code Structure

```
converter/
├── converter.py          # Main conversion script
├── direct_gltf_export.py # Direct glTF conversion
├── buffer.py            # Binary data handling
├── s3d.py               # S3D archive reader
├── wld.py               # WLD fragment parser
├── zonefile.py          # Zone data structures
├── charfile.py          # Character format (future)
├── three_js_viewer.html # Web viewer
├── output/              # Generated .glb files
└── README.md            # This file
```

## Resources

- [EverQuest File Formats](https://github.com/EQEmu/Server/wiki/File-Formats)
- [glTF Specification](https://github.com/KhronosGroup/glTF)
- [Three.js Documentation](https://threejs.org/docs/)
