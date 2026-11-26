# APMI Package current state

2026-11-26, Asia/Shanghai. APMI Core 0.2.2 DEV is installed at `F:\APMI Launcher\dist\APMI` with XXMI 1.3.3 and probe 0.1.18-apmi.1. The final installation backup is `build/deployment-20261126-135413-be1e47/`. The prior 0.2.1 Core is in `build/deployment-20261126-135000-27c2a3/`.

## Core and exporter

The export follows the structure shown in the user's EFMI screenshots and implemented by LoyalTools' merged-skeleton generator. `TextureOverride_EntryPoint_ComponentN` matches the actual IB range and base vertex and sets the draw callback. `CommandList_Component_DrawInstances` calls Core. `CommandList_Draw_ComponentN` binds resources and draws. Resource sections are named `Resource_<IB>_<IndexCount>_<FirstIndex>_<Category>`. Files use `Meshes/<IB>-<IndexCount>-<FirstIndex>-<Category>.buf`. The generated mod contains geometry and draw bindings. Core owns the compute bindings and dispatch.

The current-character sample is `build/efmi-current-character-mod/mod.ini`. It has 71 lines and four byte-exact geometry buffers, validated in `build/efmi-current-character-verification.json`. The superseded sample is archived at `build/efmi-current-character-mod-0.2.1/`.

The original 2026-11-26 dump at `dist/APMI/FrameAnalysis-2026-11-26-113431/` in the launcher workspace has 15 recognized AP components, 65,996 vertices and 93,306 triangles. AP uses 40-byte PNT, native 1/2/4-weight blends, 64-byte column-major bone matrices at `cs-t2`, a vertex-count CB and raw pose output at `cs-u0`. Core 0.2.2 copies the live palette when AP skins a position buffer and uses that buffer's identity to select the current and previous palettes at draw time. Replacement buffers are sized from the export. The mod's canonical blend uses 32-byte records. Projects retain component numbers, source bone indices and component palettes for future merged-skeleton work.

Live frame 431458 showed five `DrawIndexed` calls for `d9cf7935`. Two layouts read float3 `TEXCOORD5` in `vb3`. The nine observed previous-position VS hashes use explicit filter index 2 because XXMI returns 1 for a shader matched by the general regex without a filter. Evidence is launcher `build/ap-efmi-entrypoint-reference/reference.json`.

The field capture at 17:30 matched IB `6ee9b2ad` with 80,016 indices in draws 001189 and 001190. Core found the current palette and skipped the replacement because the previous palette timestamp was zero. Core now binds the replacement's current skinned position buffer to `vb3` when a pass needs previous positions and the previous palette is missing or stale. A valid previous palette still gets its own dispatch. When the current palette is unavailable, Core leaves the native draw in place.

## Verification on 2026-11-26

| Scenario | Observation | Evidence |
| --- | --- | --- |
| Blender 4.5.7 LTS, Core 0.2.2 | All 61 unedited export buffers matched their source bytes. Edited position, UV, weights, topology and expanded color passed. Five influences were rejected. | `build/blender-efmi-entrypoint-final/result.json` |
| Captured Core shader, 0.2.2 | All 15 native dispatches matched Core HLSL on D3D11 WARP. Maximum error `3.576e-7`. | `build/efmi-entrypoint-gpu/verification.json` |
| Native fixture, Core 0.2.2 | Published launcher 0.2.0 loaded XXMI 1.3.3 and rendered ordinary and instanced draws. Current and previous positions matched exactly. F10 loaded a 65-vertex export into a running fixture. F11 restored native drawing. | Launcher `build/tests/bd243c4c41/core-evidence.json` |
| Worker integration, Core 0.2.2 | The normal fixture rendered 90 frames. Timeout, cancellation, lock, stale log, missing DLL, early exit and already-running checks passed. | Launcher `build/tests/9d1bb468cf/` |
| Live character, Core 0.2.2 | AP PID 7776 frame 505651 captured five replacement draws and seven compute calls for `d9cf7935`. Index and attribute bytes matched. Maximum current and previous pose error was `1.192e-7`. F11 restored five native draws at frame 505875. The mod was archived outside Mods and F10 restored native draws and the Core overlay at frame 506393. | Launcher `build/ap-current-character-efmi-0.2.2-final/verified.json` and `roundtrip/verification.json` |
| Earlier live template, Core 0.2.1 | AP PID 7776 frame 377101 had one native skin dispatch and five replacement draws. F11 and cleanup restored the normal scene. | Launcher `build/ap-current-character-efmi-0.2.1/verified.json` |
| Field palette fallback | A private XXMI/D3D11 probe reproduced the skipped draw with the original Core. The patched Core passed missing, stale and valid previous palettes, missing current palette and a pass without previous positions. | `build/field-fallback-xxmi/` |
| Field fix regression | WARP matched 11 native skinning dispatches with maximum error `3.576e-7`. A Blender 5.2.2 round trip preserved all eight buffers across two components. | `build/field-fallback-warp.json` and `build/field-fallback-roundtrip-174045369/` |

See [Known issues](KNOWN_ISSUES.md) for remaining coverage. [LoyalTools integration plan](../docs/LOYALTOOLS_PLAN.md) records the proposed entry points in the existing add-on. LoyalTools has only been read. Slot caching and release publication remain deferred.
