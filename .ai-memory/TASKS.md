# APMI Package tasks

- [x] Reproduce AP compute skinning against captured dispatch inputs and outputs.
- [x] Implement APMI Core 0.2.0 and verify it through isolated XXMI/worker/GPU tests.
- [x] Extract AP meshes with raw vertex streams, per-component weight palettes and texture evidence.
- [x] Implement standalone Blender import/export and test unchanged, edited and changed-topology round trips.
- [x] Follow the user's EFMI merged-skeleton template for INI entry points, draw command lists and LoyalTools resource names. Move all compute commands into Core 0.2.2.
- [x] Extract and round-trip the current character's `d9cf7935` component. Test the generated template against real AP draws and confirm restoration after removing the temporary mod.
- [x] Prepare and present the LoyalTools integration plan before add-on changes.
- [ ] Broaden real-game coverage to edited meshes, other characters and LOD transitions.
- [ ] Capture the same character's palettes in one frame and verify the per-component bone mapping for a merged-skeleton export mode.
- [ ] Integrate into LoyalTools after scope is agreed with the user.

Work locally. Use captured AP rest geometry and component bone palettes as the authoring inputs.
