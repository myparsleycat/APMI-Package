"""Write component entry points and draw command lists in the EFMI layout."""
import json
from pathlib import Path


def section(lines, name, *commands):
    lines.extend([f'[{name}]', *commands, ''])


def write_mod(project, destination, components):
    destination = Path(destination)
    lines = ['; APMI', '']
    section(lines, 'Constants', 'global $required_apmi_version = 0.22', 'global $mod_id = -1000',
            'global $mod_enabled = 0', 'global $object_detected = 0')
    section(lines, 'Present', 'if $object_detected && $mod_id == -1000',
            '    run = CommandListRegisterMod', 'endif', 'post $object_detected = 0')

    entrypoints = ['; Component Entry Points -------------------------', '']
    draws = ['; Command Lists -------------------------', '']
    resources = ['; Resources -------------------------', '']
    section(draws, 'CommandListRegisterMod', r'$\APMIv1\required_version = $required_apmi_version',
            r'run = CommandList\APMIv1\RegisterMod', r'$mod_id = $\APMIv1\mod_id', 'if $mod_id >= 0',
            '    $mod_enabled = 1', 'endif')

    for number, component in enumerate(components):
        component_id = component.setdefault('component_id', number)
        name = f'Component{component_id}'
        unique_name = f'{component["ib_hash"]}-{component["index_count"]}-{component["first_index"]}'
        prefix = 'Resource_' + unique_name.replace('-', '_')
        meshes = destination / 'Meshes'
        folder = meshes / component['id']
        component['runtime_influences'] = 4

        draw_types = {draw['call'] for draw in component['passes']}
        count = component['export_indices']
        indexed = f'drawindexed = {count},0,0'
        instanced = f'drawindexedinstanced = {count},INSTANCE_COUNT,0,0,FIRST_INSTANCE'
        if draw_types == {'DrawIndexed'}:
            condition = 'DRAW_TYPE == 2'
            calls = [indexed]
        elif draw_types == {'DrawIndexedInstanced'}:
            condition = 'DRAW_TYPE == 4'
            calls = [instanced]
        else:
            condition = '(DRAW_TYPE == 2 || DRAW_TYPE == 4)'
            calls = ['if DRAW_TYPE == 4', '    ' + instanced, 'else', '    ' + indexed, 'endif']
        section(entrypoints, f'TextureOverride_EntryPoint_{name}', f'hash = {component["ib_hash"]}',
                f'match_first_index = {component["first_index"]}', f'match_index_count = {component["index_count"]}',
                f'match_first_vertex = {component["base_vertex"]}', '$object_detected = 1',
                f'if $mod_enabled && {condition}', rf'    $\APMIv1\component_id = {component_id}',
                r'    $\APMIv1\gpu_posed = 1', rf'    Resource\APMIv1\Input_Position = ref {prefix}_Position',
                rf'    Resource\APMIv1\Input_Blend = ref {prefix}_Blend',
                rf'    CommandList\APMIv1\Callback_Component_DrawCustom = ref CommandList_Draw_{name}',
                '    run = CommandList_Component_DrawInstances', 'endif')

        component['export_files'] = {}
        for category, key, settings in (
            ('Index', 'indices', ('type = Buffer', 'format = DXGI_FORMAT_R32_UINT')),
            ('Position', 'rest', ('type = ByteAddressBuffer', 'stride = 40')),
            ('Blend', 'blend', ('type = ByteAddressBuffer', 'stride = 32')),
        ):
            filename = f'{unique_name}-{category}.buf'
            (folder / f'{key}.buf').rename(meshes / filename)
            component['export_files'][key] = f'Meshes/{filename}'
            section(resources, f'{prefix}_{category}', *settings, rf'filename = Meshes\{filename}')

        commands = [f'ib = {prefix}_Index', r'vb0 = ref Resource\APMIv1\Position']
        slots = set()
        for stream in component['streams']:
            if stream['role'] != 'attributes':
                continue
            slot = stream['slot']
            category = {1: 'Texcoord', 3: 'Color', 4: 'Color'}.get(slot)
            if category is None or category in slots:
                raise ValueError(f'{name}: unsupported vertex streams in vb{slot}')
            slots.add(category)
            filename = f'{unique_name}-{category}.buf'
            (folder / (stream['id'] + '.buf')).rename(meshes / filename)
            stream['export_file'] = f'Meshes/{filename}'
            stride = stream['stride']
            if stride:
                stream.update(runtime_stride=stride, runtime_file=stream['export_file'])
                section(resources, f'{prefix}_{category}', 'type = Buffer', f'stride = {stride}',
                        rf'filename = Meshes\{filename}')
                commands.append(f'vb{slot} = {prefix}_{category}')
        folder.rmdir()
        section(draws, f'CommandList_Draw_{name}', *commands, *calls)

    section(draws, 'CommandList_Component_DrawInstances', r'run = CommandList\APMIv1\Component_DrawInstances')
    (destination / 'mod.ini').write_text('\n'.join([*lines, *entrypoints, *draws, *resources]), encoding='utf-8')
    manifest = dict(schema=4, game='AzurPromilia', core='APMIv1', minimum_core='0.2.2',
                    source=project['source'], components=components)
    (destination / 'export.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
