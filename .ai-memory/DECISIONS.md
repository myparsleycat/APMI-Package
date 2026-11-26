# APMI Package decisions

- Keep AP-specific bone layouts and dispatch behavior based on AP captures. Do not carry over Endfield's bone-pool assumptions.
- Test Blender through the installed 4.5.7 executable and runtime behavior through private package copies and the published APMI Launcher. Exclude user Mods from test copies.
- Deploy at the existing launcher package location; preserve its settings path and back up Core/config before replacement.
- Follow LoyalTools' merged EFMI generator for `TextureOverride_EntryPoint_ComponentN`, the separate draw callback and the IB/index-count/first-index/category resource names. Use `match_first_vertex` and draw types from AP captures.
- Keep all compute bindings and dispatches in Core. Capture each native component's palette by pose-buffer identity. Allocate replacement output buffers from the exported size and restore the native draw state. Select previous-position passes by their explicit vertex shader filter.
- Preserve component IDs, source indices and palettes for future merged-skeleton work. Derive the cross-component bone mapping from AP captures.
- Do not alter LoyalTools until its integration plan has been presented. Do not publish a release.
