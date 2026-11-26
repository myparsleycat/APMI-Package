# APMI Package

Azur Promilia runtime configuration and APMI Core 0.3.0, with frame-dump extraction and standalone Blender import/export tools.

Use this directory as the APMI Package in [APMI Launcher](https://github.com/loyal37/APMI-Launcher) after supplying the compatible XXMI 1.3.3 `d3d11.dll` and `d3dcompiler_47.dll`. The runtime files are `d3dx.ini` and `Core/APMI/`. Put mod folders in `Mods/`.

The Core configuration and UI helpers build on [EFMI-Package](https://github.com/SpectrumQT/EFMI-Package). See [LICENSE](LICENSE) and [UPSTREAM.json](UPSTREAM.json) for the GPL-3.0 license and source provenance.

## Core

The exporter uses the entry-point and draw-command layout of LoyalTools' merged-skeleton EFMI template. `TextureOverride_EntryPoint_ComponentN` matches the original draw and sets its callback. `CommandList_Component_DrawInstances` calls Core. `CommandList_Draw_ComponentN` binds the replacement buffers and issues the draw. Buffer resource names use `Resource_<IB>_<IndexCount>_<FirstIndex>_<Category>` and file names use `Meshes\<IB>-<IndexCount>-<FirstIndex>-<Category>.buf`.

- Native one-, two- and four-influence variants read source PNT from `cs-t0`, weights/indices from `cs-t1` and 64-byte bone matrices from `cs-t2`.
- Blender projects and mod exports use 40-byte PNT and a canonical 32-byte float4/uint4 blend stream. The project retains the component number, bone indices and captured matrices for future merged-skeleton work.
- `Core/APMI/main.ini` hooks the observed AP shader variants. `API.ini` copies each native palette, looks it up by the character's current or previous position buffer, and runs `CustomShaderMeshSkinner`. Core owns the compute bindings and dispatch. It restores the game's bindings after each replacement draw.
- Core allocates replacement position buffers at the exported mesh size. The private F10 test reloaded a 65-vertex mod while the original three-vertex buffers were already allocated.

Common UI/text helpers originate from the owner's EFMI package; Endfield-specific skeleton, merged-pool and shape-key code was not carried over. Source hashes are recorded in [UPSTREAM.json](UPSTREAM.json).

To deploy Core into an existing compatible working package, with its old Core and INI backed up under `build/deployment-*`:

```powershell
py -3.12 scripts/deploy_core.py 'F:/APMI Launcher/dist/APMI'
```

This changes the active Core include and copies `Core/APMI`. It retains the installation's runtime DLLs, Mods and other INI settings. Reload with F10 or restart through APMI Launcher. The development runtime DLLs must be supplied locally and match the tested copies before deployment.

## Extract, import and export

The extractor reads XXMI dumps and MCP dumps written with the XXMI log format. It uses slots declared in the input layout, pairs compute output with subsequent draws and imports the compute input geometry. Select the intended component IBs when a frame contains multiple models or LODs.

```powershell
py -3.12 tools/extract_ap.py 'F:/APMI Launcher/dist/APMI/FrameAnalysis-2026-11-26-113431'
py -3.12 tools/extract_ap.py 'F:/APMI Launcher/dist/APMI/FrameAnalysis-2026-11-26-113431' --out build/model --ib fdcaf230
& 'D:/blender4,5/blender.exe' --background --factory-startup --python-exit-code 1 --python tools/blender_ap.py -- import build/model --blend build/model/model.blend
& 'D:/blender4,5/blender.exe' --background --factory-startup --python-exit-code 1 --python tools/blender_ap.py -- export build/model --blend build/model/model.blend --out build/model-mod
```

Omit `--ib` to extract all recognized components, or repeat it to select several. Output folders must be new or empty. Export produces `mod.ini`, `export.json` and the geometry files under `Meshes/`. Place the exported folder under the active package's `Mods` to test it. `roundtrip` combines import and export.

Blender objects retain AP's native coordinates, component identity, source-vertex references, UVs, point colors and `Bone_####` vertex groups. Preserve the `ap_source_vertex` attribute. Apply mesh modifiers before exporting. A component supports one to four nonzero weights per vertex, within its captured palette. UV seams create new exported vertices as needed. Shared zero-stride attributes expand to a per-vertex stream when edited. Mirrored object transforms reverse triangle winding. `--recalculate-normals` regenerates normals and tangents; the default preserves original normal/tangent bytes.

The tools retain texture binding evidence and extract DDS files, but do not guess material roles or construct an armature hierarchy from animated skin matrices. Texture replacement, automatic character/LOD grouping, merged skeletons, shape keys and arbitrary unobserved rendering pipelines are outside this initial implementation. Geometry-only round trips preserve the game's material bindings.

## Verification

Checks on 2026-11-26 used Blender 4.5.7 LTS, XXMI 1.3.3 and launcher 0.2.0.

| Check | Result | Local evidence |
| --- | --- | --- |
| Captured native skinning | The Core 0.2.2 HLSL matched all 15 captured dispatches on D3D11 WARP. Maximum GPU error `3.576e-7`. | `build/efmi-entrypoint-gpu/verification.json` |
| Blender save/reopen/export | Core 0.2.2 exported 15 components with all 61 buffers byte-for-byte equal after save and reopen. | `build/blender-efmi-entrypoint-final/result.json` |
| Edited Blender export | Position, UV, weights, additional faces and vertices, and expanded shared color passed. The five-influence edit was rejected. | `build/blender-efmi-entrypoint-final/result.json` |
| Transforms and shading | Mirrored winding passed. Recalculated normals and tangents were finite. | `build/blender-geometry-efmi-entrypoint/result.json` |
| Generated INI and Core 0.2.2 on XXMI | The published worker fixture verified current and previous poses, F10 hot loading with extra vertices, indexed instancing and F11 native fallback. | Launcher workspace `build/tests/bd243c4c41/core-evidence.json` |
| Generic MCP on APMI Core 0.2.1 | 34 tools, F10/F11, recording, export and reconnect passed. | Launcher workspace `build/tests/b169a0e09c/mcp-evidence.json` |
| Current character in AP on Core 0.2.2 | Frame 505651 recorded five replacement draws and seven compute calls, including the two passes that read the previous pose. Index and attribute buffers were exact and maximum pose error was `1.192e-7`. F11 restored native draws at frame 505875. | Launcher workspace `build/ap-current-character-efmi-0.2.2-final/verified.json` and `roundtrip/verification.json` |

The game check covers the selected component on the tested character. Other characters, LOD transitions and visual results during movement need separate checks.

```powershell
& scripts/build-tests.ps1
py -3.12 tools/verify_skinning.py '<dump-folder>' --out build/skinning-gpu.json --gpu build/skin_gpu.exe
& 'D:/blender4,5/blender.exe' --background --factory-startup --python-exit-code 1 --python tests/blender_roundtrip.py -- build/model build/roundtrip-check
py -3.12 tests/core_runtime.py --launcher 'F:/APMI Launcher' --native-shader 'F:/APMI Launcher/build/apmi-pipeline-20261126/shaders/shaders/3b4f1b1749cd3030-cs.bin'
```

The Blender regression uses specific IBs from the supplied capture. The runtime fixture uses AP's captured one-weight shader on its own mesh. Worker tests use private package copies.

The proposed addon work is described in [the LoyalTools integration plan](docs/LOYALTOOLS_PLAN.md). No LoyalTools files have been changed.
