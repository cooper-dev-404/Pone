#!/usr/bin/env python3
"""Exercise the shipped P一下 samples with the pinned PhotoCraft CLI."""
import argparse
import csv
import json
from pathlib import Path
import struct
import tempfile
from zipfile import ZipFile

from batch_export import SRGB, asset_scales, deliver, load_recipe, render
from editor import Editor
from font_check import inspect_fonts, render_report
from link_handoff import inspect_links, linked_layers, package, write_report
from template_batch import deliver as deliver_template, template_slots


ROOT = Path(__file__).resolve().parent
def by_name(editor, document):
    return {layer['name']: layer for layer in editor.info(document)['layers']}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def psd(editor, staging):
    source = ROOT / 'sample' / '产品合成.psd'
    layers = by_name(editor, source)
    require(layers['商品原图']['hasMask'], 'source PSD lost the product mask')
    require(layers['主体曲线']['clipped'], 'source PSD lost the clipped curves adjustment')
    updated = staging / 'revised.psd'
    editor.edit(source, [
        ('type.edit', {'layer': layers['海报标题']['id'], 'text': '周末上新'}),
        ('layer.setAdjustment', {'layer': layers['主体曲线']['id'], 'points': [[0, 0], [128, 162], [255, 255]]}),
    ], updated)
    changed = by_name(editor, updated)
    require(changed['海报标题']['text']['text'] == '周末上新', 'reopened PSD title did not update')
    require(changed['主体曲线']['adjustment']['params']['points'][1] == [128.0, 162.0],
            'reopened PSD curves did not update')
    require(changed['主体曲线']['clipped'] and changed['商品原图']['hasMask'],
            'reopened PSD lost clipping or source mask')
    return {'layers': len(changed), 'title': '周末上新', 'curves_middle': [128, 162],
            'clipping_retained': True, 'mask_retained': True}


def local_font(editor, staging, family):
    source = ROOT / 'sample' / '精修素材.png'
    font_list, family_info = editor.edit(source, [('type.fonts', {}), ('type.fonts', {'family': family})])
    faces = family_info['result']['faces']
    require(family in font_list['result']['families'] and faces, f'Font is not listed by the text engine: {family}')
    installed_names = {face['postscriptName'] for face in faces if face['postscriptName']}
    require(installed_names, f'No PostScript face name found for {family}')

    created = staging / '本地字体.pcraft'
    title = '本地字体测试'
    original_text, updated_text = 'Local font Aa 2026', 'Revised text Aa 2026'
    editor.edit(source, [('type.create', {
        'name': title, 'text': original_text, 'font': family, 'size': 24, 'x': 20, 'y': 70,
    })], created)

    def check_text(document, expected):
        layer = by_name(editor, document)[title]
        [info] = editor.edit(document, [('type.info', {'layer': layer['id']})])
        details = info['result']
        style = details['runs'][0]['style']
        require(layer['kind'] == 'Type' and details['text'] == expected, f'{document.name} lost editable text')
        require(style['font_family'] == family and style['postscript_name'] in installed_names and not details.get('warnings'),
                f'{document.name} did not resolve to an installed face of {family}')
        require(details['bounds'] and details['bounds'][2] > details['bounds'][0], f'{document.name} did not render text')
        return style['postscript_name']

    face = check_text(created, original_text)
    psd_path = staging / '本地字体.psd'
    editor.call('convert', created, psd_path)
    require(check_text(psd_path, original_text) == face, 'Layered PSD changed the local font face')
    edited = staging / '本地字体改字.psd'
    layer_id = by_name(editor, psd_path)[title]['id']
    editor.edit(psd_path, [('type.edit', {'layer': layer_id, 'text': updated_text, 'name': title})], edited)
    require(check_text(edited, updated_text) == face, 'Editing reopened PSD changed the local font face')
    return {'family': family, 'faces': len(faces), 'postscript_name': face, 'pcraft_reopened': True, 'psd_reedited': True}


def font_report(editor, staging):
    template = ROOT / 'templates' / '商品上新模板.pcraft'
    board = '社媒方图'
    label = '活动标题 <主标题>'
    group = '标题校对组'
    missing = ['Layerlight Proof Missing Sans', 'Layerlight Proof Missing Serif']
    staged = staging / '字体交接样稿.pcraft'
    editor.edit(template, [
        ('layer.select', {'layer': by_name(editor, template)[board]['id']}),
        ('type.create', {'name': label, 'text': 'Studio 2026', 'font': missing[1], 'size': 36, 'x': 1550, 'y': 100}),
        ('type.setStyle', {'range': [7, 11], 'font': missing[0]}),
        ('layer.new.groupFromLayers', {'name': group}),
        ('layer.setProps', {'visible': False}),
    ], staged)
    cases = [staged]
    for extension in ('psd', 'psb'):
        document = staged.with_suffix('.' + extension)
        editor.call('convert', staged, document)
        cases.append(document)
    original_files = {document: document.read_bytes() for document in cases}
    for document in cases:
        total, affected, unlocated = inspect_fonts(editor, document)
        require(total > 1 and len(affected) == 1 and not unlocated, f'{document.suffix} did not locate just the affected layer')
        [(path, layer_id, visible, families)] = affected
        require(layer_id and path == (board + '（画板）', group, label) and not visible and families == missing,
                f'{document.suffix} lost mixed font names, nesting or inherited visibility')
    corrupt = staging / '损坏样稿.psb'
    corrupt.write_bytes(b'Invalid image data')
    report = render_report(editor, [*cases, corrupt])
    require('共 4 份稿件，3 个文字图层缺字体，1 份稿件无法检查。' in report, 'font report did not handle unreadable input')
    require('&lt;主标题&gt;' in report and '<主标题>' not in report, 'font report did not escape layer names')
    require(all(document.read_bytes() == before for document, before in original_files.items()),
            'font inspection changed source files')
    return {'formats': [document.suffix for document in cases], 'families_on_one_layer': missing,
            'hidden_layer_path_retained': True, 'unreadable_file_isolated': True, 'source_unchanged': True}


def linked_handoff(editor, staging):
    first = staging / 'amber' / '相机.png'
    second = staging / 'blue' / '相机.png'
    for destination, image in [(first, '琥珀款.png'), (second, '海蓝款.png')]:
        destination.parent.mkdir()
        destination.write_bytes((ROOT / 'templates' / image).read_bytes())
    source = staging / '商品链接.pcraft'
    editor.edit(ROOT / 'sample' / '产品合成.psd', [
        ('file.placeLinked', {'path': str(first), 'center': [420, 380], 'scale': 40}),
        ('edit.transform', {'rotate': 7}),
        ('layer.setProps', {'name': '左侧相机'}),
        ('layer.duplicate', {}),
        ('layer.setProps', {'name': '左侧相机副本'}),
        ('edit.transform', {'dx': -100, 'dy': 40}),
        ('file.placeLinked', {'path': str(second), 'center': [680, 390], 'scale': 40}),
        ('layer.setProps', {'name': '右侧相机'}),
        ('layer.new.groupFromLayers', {'name': '产品图组'}),
    ], source)
    source_bytes = source.read_bytes()
    assets = inspect_links(editor, source)
    require(len(assets) == 2 and not any(asset['issue'] for asset in assets), 'link check did not open both sources')
    original_layers = list(linked_layers(editor.info(source)['layers']))
    shared = next(item for item in assets if item['path'] == str(first))['layers']
    require(len(shared) == 2 and len({layer['contents'] for layer in shared}) == 1, 'fixture did not create shared instances')
    probe = (406, 400)
    before = editor.pixel(source, *probe)
    relocation = staging / 'relocated-asset'
    relocation.mkdir()
    moved_file = first.rename(relocation / first.name)
    report = write_report(editor, source, staging / 'link-reports').read_text(encoding='utf-8')
    require('左侧相机副本' in report and '产品图组 › 右侧相机' in report and '1 个来源无法读取' in report,
            'link check did not report the broken source, shared instances and nested placement')

    target = staging / 'handoffs'
    try:
        package(editor, source, target)
    except RuntimeError as error:
        require('重新链接' in str(error) and not any(target.iterdir()), 'failed package did not explain or clean up missing links')
    else:
        raise RuntimeError('package published a document with a missing link')

    repaired = package(editor, source, target, [(shared[0]['layer'], str(moved_file))])
    manifest = json.loads((repaired / '链接清单.json').read_text(encoding='utf-8'))
    moved = repaired.rename(staging / '迁移之后')
    document = moved / manifest['document']
    actual = inspect_links(editor, document)
    require(len(actual) == 2 and all(asset['path'].startswith('Links/') and not asset['issue'] for asset in actual),
            'package did not reopen all links from the relocated folder')
    require(sorted(len(item['layers']) for item in manifest['links']) == [1, 2], 'package did not deduplicate shared sources')
    require({(moved / item['file']).read_bytes() for item in manifest['links']} == {moved_file.read_bytes(), second.read_bytes()},
            'package changed or overwrote the same-name linked files')
    require(editor.pixel(document, *probe) == before, 'rendered sample changed after relink and relocation')
    repaired_layers = list(linked_layers(editor.info(document)['layers']))
    require({(layer['layer_path'], layer['contents']) for layer in original_layers} ==
            {(layer['layer_path'], layer['contents']) for layer in repaired_layers}, 'package lost a placement or shared contents identity')
    for name in ['左侧相机', '左侧相机副本']:
        require(smart_content(document, name)['transform'] == smart_content(source, name)['transform'],
                'relink altered a smart object placement')
    require(source.read_bytes() == source_bytes, 'check, relink or package wrote to the original project')
    return {'source_files': 2, 'linked_layers': 3, 'missing_link_reported': True, 'blocked_package_cleaned': True,
            'relink_preserved_transform': True, 'moved_package_reopened': True, 'source_unchanged': True}


def smart_content(document, name):
    with ZipFile(document) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    layer = next(layer for layer in manifest['document']['layers'] if layer['name'] == name)
    return layer['content']


def complex_psd(editor, staging):
    source = ROOT / 'sample' / '产品合成.psd'
    image = staging / '横幅素材.png'
    placed = staging / '组合.pcraft'
    changed = staging / '替换后.pcraft'
    exported = staging / '交接.psd'
    editor.call('convert', source, image)
    editor.edit(source, [
        ('layer.select', {'layer': '商品原图'}),
        ('layer.select', {'layer': '主体曲线', 'mode': 'add'}),
        ('layer.new.groupFromLayers', {'name': '商品组', 'mode': 'Normal', 'opacity': 90}),
        ('layer.setProps', {'blend': 'multiply'}),
        ('file.placeEmbedded', {'path': str(image), 'scale': 15, 'smartObject': True, 'center': [760, 530]}),
        ('edit.transform', {'rotate': 14, 'dx': 12, 'dy': 10}),
    ], placed)
    editor.edit(placed, [
        ('layer.select', {'layer': '横幅素材'}),
        ('layer.smartObjects.replaceContents', {'path': str(ROOT / 'sample' / '精修素材.png')}),
    ], changed)
    before = smart_content(placed, '横幅素材')
    after = smart_content(changed, '横幅素材')
    require(before['source'] != after['source'], 'smart object source was not replaced')
    require(before['transform'] == after['transform'], 'smart object transform changed during replacement')

    editor.call('convert', changed, exported)
    reopened = by_name(editor, exported)
    group = reopened['商品组']
    children = {layer['name']: layer for layer in group['children']}
    require(group['kind'] == 'Group' and group['blend'] == 'Multiply', 'PSD lost the blend group')
    require(abs(group['opacity'] - .9) <= 1 / 255, 'PSD opacity exceeded one byte value of quantization')
    require(children['商品原图']['hasMask'] and children['主体曲线']['clipped'],
            'PSD lost the mask or the clipping inside the group')
    require(reopened['横幅素材']['kind'] == 'Smart Object' and reopened['海报标题']['kind'] == 'Type',
            'PSD rasterized a smart object or text layer')

    high_depth = staging / '交接16位.psd'
    editor.edit(exported, [('image.mode.bits16', {})], high_depth)
    require(editor.info(high_depth)['depth'] == 16, '16-bit PSD reopened at another depth')
    return {
        'smart_transform_retained': True, 'smart_source_replaced': True,
        'group_blend': group['blend'], 'group_opacity_after_psd': group['opacity'],
        'nested_mask_and_clipping_retained': True, 'text_and_smart_object_retained': True,
        'psd_16_bit_reopened': True,
    }


def rgb_error(a, b):
    return max(abs(left - right) for left, right in zip(a[:3], b[:3]))


def rendered_rows(editor, document, target):
    editor.call('convert', document, target, '--tga-bits', 32, '--metadata', 'none')
    tga = target.read_bytes()
    width, height = struct.unpack_from('<HH', tga, 12)
    require(tga[1:3] == b'\x00\x0a' and tga[16] == 32 and not tga[17] & 16,
            'expected left-to-right RLE BGRA from the editor')
    cursor = 18 + tga[0]
    pixels = bytearray()
    while len(pixels) < width * height * 4:
        packet = tga[cursor]
        cursor += 1
        count = (packet & 127) + 1
        if packet & 128:
            pixels.extend(tga[cursor:cursor + 4] * count)
            cursor += 4
        else:
            pixels.extend(tga[cursor:cursor + 4 * count])
            cursor += 4 * count
    require(len(pixels) == width * height * 4, 'TGA packet overruns the canvas')
    stride = width * 4
    rows = [pixels[i:i + stride] for i in range(0, len(pixels), stride)]
    if not tga[17] & 32:
        rows.reverse()
    return rows


def content_aware_fill(editor, staging):
    exercise = ROOT / 'sample' / '内容识别填充练习.pcraft'
    finished = ROOT / 'verification' / '内容识别填充成稿.pcraft'
    reference = ROOT / 'verification' / '内容识别填充参考.png'
    portable = ROOT / 'presets' / 'P一下 内容识别填充.atn'
    source_bytes = exercise.read_bytes()
    [preset] = [action for action in json.loads((ROOT / 'profile' / 'actions.json').read_text(encoding='utf-8'))['actions']
                if action['set'] == 'P一下 · 内容识别填充']
    name = preset['name']
    load_channel = ('select.loadSelection', {'channel': '纸屑选区'})
    action_steps = [
        load_channel, ('actions.load', {'path': str(portable)}),
        ('actions.get', {'action': name}), ('actions.play', {'action': name}),
    ]
    quick = staging / 'fill-action.pcraft'
    _, imported, recorded, played = editor.edit(exercise, action_steps, quick)
    require(not imported['result']['unsupported'] and not imported['result']['warnings']
            and recorded['result']['set'] == preset['set'] and recorded['result']['steps'] == preset['steps'],
            'portable fill action differs from the desktop preset')
    require(played['result']['ran'] == 1 and 'failed' not in played['result'], 'fill action failed to play')

    custom = staging / 'fill-custom.pcraft'
    strokes = [
        {'mode': 'add', 'size': 35, 'points': [[672, 291], [798, 291]]},
        {'mode': 'add', 'size': 35, 'points': [[672, 374], [798, 374]]},
        {'mode': 'add', 'size': 32, 'points': [[796, 309], [796, 353]]},
    ]
    _, custom_fill = editor.edit(exercise, [load_channel, ('edit.contentAwareFill', {
        'sampling': 'custom', 'samplingStrokes': strokes, 'colorAdaptation': 'none',
        'sampleAllLayers': True, 'output': 'new',
    })], custom)
    x, y, width, height = 701, 309, 69, 48
    require(custom_fill['result']['filled'] == width * height, 'sampling strokes did not fill the whole selection')
    require(custom_fill['result']['window'] == [654, 273, 163, 120], 'custom sample did not stay near the strokes')

    tga = staging / 'caf-render.tga'
    original = rendered_rows(editor, exercise, tga)
    clean = rendered_rows(editor, reference, tga)
    left, right = x * 4, (x + width) * 4

    def check_outside(rows):
        require(len(rows) == len(original) and all(
            row[:left] == before[:left] and row[right:] == before[right:] if y <= i < y + height else row == before
            for i, (row, before) in enumerate(zip(rows, original))
        ), 'fill changed pixels outside the selection')

    def mean_rgb_error(rows):
        total = sum(abs(row[i] - ref[i]) for row, ref in zip(rows[y:y + height], clean[y:y + height])
                    for i in range(left, right) if i % 4 != 3)
        return total / (width * height * 3)

    quick_pixels = rendered_rows(editor, quick, tga)
    custom_pixels = rendered_rows(editor, custom, tga)
    errors = {key: mean_rgb_error(rows) for key, rows in
              [('original', original), ('action', quick_pixels), ('custom_sampling', custom_pixels)]}
    for rows, key in [(quick_pixels, 'action'), (custom_pixels, 'custom_sampling')]:
        check_outside(rows)
        require(errors[key] < errors['original'] / 2, f'{key} did not sufficiently reduce the test blemish')
    require(rendered_rows(editor, finished, tga) == custom_pixels, 'finished sample differs from the custom sampling result')
    require(quick_pixels != custom_pixels, 'custom sampling and the desktop preset produced identical results')

    layers = by_name(editor, finished)
    require(len(layers) == 2 and '产品原片' in layers, 'saved fill did not preserve a separate source layer')
    [repair] = [layer for layer in layers.values() if layer['name'] != '产品原片']
    require(repair['kind'] == 'Pixel' and repair['bounds'] == [x, y, width, height],
            'reopened repair layer is not an editable patch limited to the selection')
    hidden = staging / 'fill-hidden.pcraft'
    adjusted = staging / 'fill-adjusted.pcraft'
    editor.edit(finished, [('layer.setProps', {'layer': repair['id'], 'visible': False})], hidden)
    editor.edit(finished, [('layer.setProps', {'layer': repair['id'], 'opacity': 0.5})], adjusted)
    require(rendered_rows(editor, hidden, tga) == original, 'hiding the repair layer did not restore the source')
    half_opacity = rendered_rows(editor, adjusted, tga)
    require(half_opacity != original and half_opacity != custom_pixels, 'repair opacity could not be edited after reopening')
    check_outside(half_opacity)

    undone = staging / 'fill-undone.pcraft'
    editor.edit(exercise, [*action_steps, ('history.undo', {})], undone)
    require(list(by_name(editor, undone)) == ['产品原片'] and rendered_rows(editor, undone, tga) == original,
            'a single undo did not recover the source layer and pixels')
    invalid = staging / 'fill-invalid.pcraft'
    try:
        editor.edit(exercise, [load_channel, ('edit.contentAwareFill', {'sampling': 'custom', 'output': 'new'})], invalid)
    except RuntimeError as error:
        require('custom sampling needs' in str(error) and not invalid.exists(), 'invalid sampling left a partial fill')
    else:
        raise RuntimeError('custom fill accepted an empty sample area')
    require(exercise.read_bytes() == source_bytes, 'fill modified the exercise file')
    return {'selection': [x, y, width, height], 'sampling_brush_window': custom_fill['result']['window'],
            'outside_selection_pixels_identical': len(original) * (len(original[0]) // 4) - width * height,
            'selection_mean_rgb_error_8bit': {key: round(value, 2) for key, value in errors.items()},
            'repair_layer_reopened_and_edited': True, 'undo_restored_original': True,
            'invalid_custom_sampling_rejected': True, 'source_unchanged': True}


def remove_tool(editor, staging):
    exercise = ROOT / 'sample' / '移除工具练习.pcraft'
    finished = ROOT / 'verification' / '移除工具成稿.pcraft'
    reference = ROOT / 'verification' / '内容识别填充参考.png'
    source_bytes = exercise.read_bytes()
    tga = staging / 'remove-render.tga'
    original = rendered_rows(editor, exercise, tga)
    clean = rendered_rows(editor, reference, tga)
    ring = {'points': [[701, 310], [735, 309], [768, 317], [770, 345],
                       [761, 361], [716, 354], [700, 343], [701, 310]], 'size': 12}
    brush = {'points': [[577, 482], [591, 478], [604, 478], [614, 483], [626, 492]], 'size': 19}
    settings = {'sampleAllLayers': True, 'newLayer': True, 'closeLoops': True}
    subjects = {'paper': (709, 314, 764, 355), 'fiber': (575, 474, 629, 496)}
    footprints = {'paper': (691, 299, 780, 370), 'fiber': (563, 464, 638, 505)}

    def error(rows, rect):
        x0, y0, x1, y1 = rect
        total = sum(abs(row[i] - ref[i]) for row, ref in zip(rows[y0:y1], clean[y0:y1])
                    for i in range(4 * x0, 4 * x1) if i % 4 != 3)
        return total / ((y1 - y0) * (x1 - x0) * 3)

    def check_outside(rows, targets):
        # The two footprints are on distinct rows in the exercise.
        untouched = 0
        require(len(rows) == len(original), 'removal changed the canvas height')
        for y, (after, before) in enumerate(zip(rows, original)):
            require(len(after) == len(before), 'removal changed the canvas width')
            for target in targets:
                x0, y0, x1, y1 = footprints[target]
                if y0 <= y < y1:
                    require(after[:4 * x0] == before[:4 * x0] and after[4 * x1:] == before[4 * x1:],
                            f'{target} removal changed pixels beyond the brush')
                    untouched += len(before) // 4 - (x1 - x0)
                    break
            else:
                require(after == before, 'removal changed an unrelated row')
                untouched += len(before) // 4
        return untouched

    baseline = {name: error(original, rect) for name, rect in subjects.items()}
    results = {}
    for mode, strokes, targets in [
        ('closed_stroke', ring, ('paper',)),
        ('painted_stroke', brush, ('fiber',)),
        ('combined_strokes', {'strokes': [ring, brush]}, ('paper', 'fiber')),
    ]:
        removal = ('paint.remove', {**settings, **strokes})
        repaired = staging / f'remove-{mode}.pcraft'
        [result] = editor.edit(exercise, [removal], repaired)
        layers = editor.info(repaired)['layers']
        require(len(layers) == 2 and layers[0]['kind'] == 'Pixel' and layers[0]['id'] == result['result']['layer']
                and layers[1]['name'] == '产品原片', f'{mode} did not create an independent repair above the source')
        rows = rendered_rows(editor, repaired, tga)
        protected = check_outside(rows, targets)
        errors = {name: error(rows, subjects[name]) for name in targets}
        require(all(value < 0.75 * baseline[name] for name, value in errors.items()),
                f'{mode} did not restore the texture under the blemish')
        undone = staging / f'remove-{mode}-undone.pcraft'
        editor.edit(exercise, [removal, ('history.undo', {})], undone)
        require(list(by_name(editor, undone)) == ['产品原片'] and rendered_rows(editor, undone, tga) == original,
                f'{mode} did not undo the whole repair in one step')
        results[mode] = {'rgb_error_8bit': {name: round(value, 2) for name, value in errors.items()},
                         'outside_repair_footprints_identical': protected}

    # A round brush whose loop handling is disabled must leave the object at the centre.
    [mere_outline, center] = editor.edit(exercise, [
        ('paint.remove', {**settings, **ring, 'closeLoops': False}),
        ('document.pixel', {'x': 736, 'y': 335}),
    ])
    require(mere_outline['result']['layer'] and center['result'] == editor.pixel(exercise, 736, 335),
            'the loop control did not distinguish enclosing from brushing')

    from_blank = staging / 'remove-from-blank.pcraft'
    editor.edit(exercise, [('layer.new.layer', {'name': '取样测试空白层'}),
                          ('paint.remove', {**settings, 'strokes': [ring, brush]})], from_blank)
    finished_rows = rendered_rows(editor, finished, tga)
    require(finished_rows == rendered_rows(editor, staging / 'remove-combined_strokes.pcraft', tga)
            and finished_rows == rendered_rows(editor, from_blank, tga),
            'saved result changed, or Remove failed to sample the visible image from a blank layer')
    [repair, source] = editor.info(finished)['layers']
    require(source['name'] == '产品原片' and repair['kind'] == 'Pixel', 'finished example lost editable layers')
    hidden = staging / 'remove-hidden.pcraft'
    adjusted = staging / 'remove-adjusted.pcraft'
    editor.edit(finished, [('layer.setProps', {'layer': repair['id'], 'visible': False})], hidden)
    editor.edit(finished, [('layer.setProps', {'layer': repair['id'], 'opacity': 0.5})], adjusted)
    require(rendered_rows(editor, hidden, tga) == original, 'hiding the repair layer did not recover the original')
    adjusted_rows = rendered_rows(editor, adjusted, tga)
    require(adjusted_rows != original and adjusted_rows != finished_rows, 'reopened repair opacity did not change')
    check_outside(adjusted_rows, subjects)
    require(exercise.read_bytes() == source_bytes, 'removal rewrote the supplied exercise')
    return {'before_rgb_error_8bit': {name: round(value, 2) for name, value in baseline.items()},
            'modes': results, 'loop_enclosure_verified': True, 'sampled_from_blank_layer': True,
            'one_step_undo': True, 'reopened_repair_editable': True, 'source_unchanged': True}


def edge_refinement(editor, staging):
    exercise = ROOT / 'sample' / '半透明边缘练习.pcraft'
    finished = ROOT / 'verification' / '半透明边缘成稿.pcraft'
    portable = ROOT / 'presets' / 'P一下 边缘精修.atn'
    presets = [action for action in json.loads((ROOT / 'profile' / 'actions.json').read_text(encoding='utf-8'))['actions']
               if action['set'] == 'P一下 · 边缘精修']
    import_set = ('actions.load', {'path': str(portable)})
    load_channel = ('select.loadSelection', {'channel': '起始选区 · 色彩范围'})
    fringe = (511, 316)

    def native_layers(document):
        with ZipFile(document) as archive:
            items = json.loads(archive.read('manifest.json'))['document']['layers']
        return {item['name']: item for item in items}

    raw_layer = native_layers(exercise)['轻纱原片']['content']
    cutouts, pixels = [], []
    require(len(presets) == 3, 'expected three edge actions')
    for index, preset in enumerate(presets):
        name = preset['name']
        output = staging / f'edge-{index}.pcraft'
        loaded, info, _, played = editor.edit(exercise, [
            import_set, ('actions.get', {'action': name}), load_channel, ('actions.play', {'action': name}),
        ], output)
        require(not loaded['result']['unsupported'] and info['result']['set'] == preset['set'] and
                info['result']['steps'] == preset['steps'], f'{name} differs between the ATN and desktop preset')
        require('failed' not in played['result'] and played['result']['ran'] == len(preset['steps']),
                f'{name} failed during playback')
        layers = native_layers(output)
        original = layers['轻纱原片']
        require(not original['visible'] and original['content'] == raw_layer, f'{name} changed the source pixels')
        [cutout] = [layer for layer in layers.values() if layer['visible']]
        require(cutout['content']['kind'] == 'raster' and cutout['mask']['enabled'], f'{name} lost the editable mask')
        cutouts.append(cutout)
        pixels.append(editor.pixel(output, *fringe))
    plain, refined, cleaned = cutouts
    require(plain['mask']['surface'] != refined['mask']['surface'], 'edge refinement did not change the mask')
    require(refined['mask']['surface'] == cleaned['mask']['surface'], 'decontamination changed mask coverage')
    require(refined['content'] != cleaned['content'], 'decontamination did not change foreground pixels')

    # Known foreground RGBA before the synthetic fabric was composited over the studio background.
    reference = [value / 255 for value in (232, 163, 112, 60)]
    require(0 < pixels[0][3] < pixels[1][3] < 1 and abs(pixels[2][3] - reference[3]) < 1.5 / 255,
            'the test fringe lost partial transparency')
    require(rgb_error(pixels[2], reference) < rgb_error(pixels[1], reference) / 2,
            'decontamination did not reduce the studio colour cast at the test fringe')

    name = '去边色 · 可编辑蒙版'
    supplied = native_layers(finished)[name]
    require(supplied['mask'] == cleaned['mask'] and supplied['content'] == cleaned['content'],
            'replayed actions differ from the shipped finished sample')
    for comp, expected in [('黑底预览', (26, 32, 38)), ('白底预览', (246, 244, 239))]:
        _, outside, blended = editor.edit(finished, [
            ('layerComp.apply', {'comp': comp}), ('document.pixel', {'x': 13, 'y': 20}),
            ('document.pixel', {'x': fringe[0], 'y': fringe[1]}),
        ])
        background = [v / 255 for v in expected]
        require(rgb_error(outside['result'], background) <= 1 / 255 and outside['result'][3] == 1,
                f'{comp} has the wrong background')
        alpha = pixels[2][3]
        composite = [alpha * fg + (1 - alpha) * bg for fg, bg in zip(pixels[2][:3], background)]
        require(rgb_error(blended['result'], composite) <= 2 / 255 and blended['result'][3] == 1,
                f'{comp} has the wrong translucent edge')
    for comp, expected in [('原片', editor.pixel(exercise, *fringe)), ('透明底', pixels[2])]:
        _, observed = editor.edit(finished, [
            ('layerComp.apply', {'comp': comp}), ('document.pixel', {'x': fringe[0], 'y': fringe[1]}),
        ])
        require(observed['result'] == expected, f'{comp} did not restore the expected RGBA')

    edited = staging / 'mask-edit.pcraft'
    select_layer = ('layer.select', {'layer': name})
    editor.edit(finished, [select_layer, ('layer.layerMask.edit', {'density': 50})], edited)
    require(abs(editor.pixel(edited, *fringe)[3] - (1 + pixels[2][3]) / 2) <= 1 / 255,
            'mask density did not survive save/reopen')
    editor.edit(finished, [select_layer, ('paint.stroke', {
        'target': 'mask', 'points': [fringe], 'color': '#ffffff', 'size': 18, 'hardness': 1,
    })], edited)
    painted = editor.pixel(edited, *fringe)
    require(painted[3] == 1 and native_layers(edited)[name]['content'] == supplied['content'] and
            editor.pixel(edited, 400, 280) == editor.pixel(finished, 400, 280),
            'mask painting changed image pixels or the mask beyond its stroke')
    return {'actions_replayed': len(presets), 'original_pixels_preserved': True, 'decontamination_kept_mask': True,
            'fringe_xy': list(fringe), 'before_rgb_decontamination': pixels[1], 'after_rgb_decontamination': pixels[2],
            'mask_paint_and_density_reopened': True, 'layer_comps_checked': ['原片', '透明底', '黑底预览', '白底预览']}


def retouch(editor, staging):
    source = ROOT / 'sample' / '精修素材.png'
    target = (790, 208)
    sample = (749, 208)
    original = editor.pixel(source, *target)
    clean = editor.pixel(source, *sample)
    outputs = {}
    recipes = [
        ('污点修复', 'paint.spotHealing', {'size': 60, 'hardness': 80, 'sampleAllLayers': True}),
        ('仿制图章', 'paint.cloneStamp', {'size': 52, 'hardness': 100, 'source': sample, 'sampleLayer': 'all'}),
    ]
    for title, command, params in recipes:
        updated = staging / f'{title}.pcraft'
        editor.edit(source, [('layer.new.layer', {'name': title}), (command, {'points': [target], **params})], updated)
        layers = by_name(editor, updated)
        require(len(layers) == 2 and layers[title]['kind'] == 'Pixel', 'retouch flattened the original layer')
        pixel = editor.pixel(updated, *target)
        require(rgb_error(original, clean) > .25 and rgb_error(pixel, clean) < .07,
                f'{title} did not remove the test blemish')
        require(editor.pixel(updated, 120, 120) == editor.pixel(source, 120, 120),
                f'{title} modified a pixel outside the stroke')
        outputs[title] = {'before_rgb': original[:3], 'after_rgb': pixel[:3], 'separate_layer': True}
    return outputs


def artboards(editor, staging):
    document = ROOT / 'sample' / '横竖版交付.pcraft'
    folder = staging / 'artboards'
    folder.mkdir()
    editor.edit(document, [('file.export.artboardsToFiles', {'dir': str(folder), 'format': 'png', 'prefix': 'asset-'})])
    results = {}
    for file in folder.glob('*.png'):
        with file.open('rb') as source:
            header = source.read(29)
        require(header[:8] == b'\x89PNG\r\n\x1a\n', f'{file} is not a PNG')
        width, height = struct.unpack('>II', header[16:24])
        board = '竖版' if '竖版' in file.name else '横版'
        results[board] = {'pixels': [width, height], 'color_type': header[25]}
    require(results.get('横版', {}).get('pixels') == [960, 540], 'landscape artboard gave wrong dimensions')
    require(results.get('竖版', {}).get('pixels') == [480, 640], 'portrait artboard gave wrong dimensions')
    require(results['竖版']['color_type'] in [4, 6], 'portrait artboard lost its alpha channel')
    return results


def batch_delivery(editor, staging):
    source = ROOT / 'sample' / '产品合成.psd'
    boards = ROOT / 'sample' / '横竖版交付.pcraft'
    variants, formats = load_recipe(ROOT / 'batch_recipe.json')
    target = staging / 'batches'
    before = source.read_bytes()
    folder = deliver(editor, [source, boards], variants, formats, target)
    manifest = json.loads((folder / '交付清单.json').read_text(encoding='utf-8'))
    outputs = [entry for doc in manifest['documents'] for entry in doc['outputs']]
    require(len(outputs) == 7 and all(entry['embedded_icc'].startswith('sRGB') for entry in outputs),
            'batch delivery did not produce all seven tagged files')
    transparent = [entry for entry in outputs if entry.get('artboard') == '竖版' or entry.get('fit') == 'contain']
    require(len(transparent) == 4 and
            all(editor.pixel(folder / entry['file'], 0, 0)[3] == 0 for entry in transparent),
            'letterboxed variants or transparent artboards lost alpha')
    require(source.read_bytes() == before, 'batch export modified the source PSD')

    bad = staging / '损坏.png'
    bad.write_bytes(b'invalid source')
    try:
        deliver(editor, [source, bad], variants, formats, target)
    except RuntimeError:
        pass
    else:
        raise RuntimeError('batch delivery accepted an unreadable source')
    require(list(target.iterdir()) == [folder], 'failed batch left behind a partial delivery')
    return {'files': len(outputs), 'embedded_srgb': True, 'alpha_preserved': True,
            'source_verified': True, 'partial_delivery_cleanup': True}


def asset_delivery(editor, staging):
    sample = ROOT / 'sample' / '素材出图.pcraft'
    variants, formats = load_recipe(ROOT / 'batch_recipe.json')
    target = staging / 'assets'
    source_bytes = sample.read_bytes()
    completed = deliver(editor, [sample], variants, formats, target, mode='assets', prefix='上新')
    manifest = json.loads((completed / '交付清单.json').read_text(encoding='utf-8'))
    entries = manifest['documents'][0]['outputs']
    base_sizes = {'商品透明图': (445, 318), '标题区域': (495, 216), '商品局部': (552, 433)}
    for item in entries:
        if item['name'] == '上新文字' and item['format'] == 'png' and item['scale'] == 1:
            require(0 < item['pixels'][0] < 960 and 0 < item['pixels'][1] < 720, 'type export did not trim the canvas')
            base_sizes['上新文字'] = item['pixels']
    require(len(entries) == 16 and {item['name'] for item in entries} == set(base_sizes),
            'asset export omitted a marked layer or manual slice')
    for item in entries:
        require(item['pixels'] == [int(side * item['scale']) for side in base_sizes[item['name']]],
                'asset export changed the expected dimensions')
    product_images = [item for item in entries if item['name'] == '商品透明图']
    require(all(editor.pixel(completed / item['file'], 0, 0)[3] == 0 for item in product_images),
            'PNG or WebP export lost transparent pixels on the masked product')

    composite = staging / 'asset-composite.tif'
    reference = staging / 'asset-reference.png'
    editor.call('convert', sample, composite, '--tiff-transparency', 'on', '--metadata', 'none')
    render(editor, composite, reference, None, [SRGB])
    x, y = 280, 210  # The same point belongs to both overlapping slices.
    pixel = editor.pixel(reference, x, y)
    overlap = [item for item in entries if item['kind'] == 'slice' and item['format'] == 'png' and item['scale'] == 1]
    require(len(overlap) == 2 and all(
        editor.pixel(completed / item['file'], x - item['rect'][0], y - item['rect'][1]) == pixel for item in overlap
    ), 'overlapping slices did not independently match the composite at their crop coordinates')

    duplicate = staging / '同名素材.psd'
    layers = by_name(editor, sample)
    [slice_info] = editor.edit(sample, [('slice.list', {})])
    rename = [('slice.set', {'slice': item['id'], 'name': '局部'}) for item in slice_info['result']['slices']
              if item['origin'] == 'user']
    editor.edit(sample, [
        *rename,
        ('layer.select', {'layer': layers['导出：上新文字']['id']}),
        ('layer.new.groupFromLayers', {'name': '标题组'}),
        ('layer.new.layer', {'name': '导出：隐藏示例'}),
        ('layer.setProps', {'visible': False}),
    ], duplicate)
    rerun = deliver(editor, [duplicate], variants, [('png', None)], target, mode='assets', scales=asset_scales('1.5'))
    files = json.loads((rerun / '交付清单.json').read_text(encoding='utf-8'))['documents'][0]['outputs']
    slices = [file for file in files if file['kind'] == 'slice']
    require(len(files) == 4 and len(slices) == 2 and len({file['file'] for file in slices}) == 2 and
            {tuple(file['pixels']) for file in slices} == {(743, 324), (828, 650)},
            'PSD duplicate names or fractional scales produced missing or incorrect files')
    require(any(file.get('layer_path') == ['标题组', '导出：上新文字'] for file in files),
            'asset export missed a named layer in a group')
    require(sample.read_bytes() == source_bytes, 'asset export changed the source project')
    return {'files': len(entries), 'transparent_layer_retained': True, 'overlapping_slices_independent': True,
            'same_name_psd_slices': len(slices), 'fractional_scale': 1.5, 'source_unchanged': True}


def template_delivery(editor, staging):
    template = ROOT / 'templates' / '商品上新模板.pcraft'
    data = ROOT / 'templates' / '商品清单.csv'
    original_bytes = template.read_bytes()
    _, formats = load_recipe(ROOT / 'batch_recipe.json')
    target = staging / 'templates'
    folder, warnings = deliver_template(editor, template, data, target, formats, 'contain')
    manifest = json.loads((folder / '套版清单.json').read_text(encoding='utf-8'))
    with data.open(encoding='utf-8-sig', newline='') as source:
        rows = list(csv.DictReader(source))

    def contents(document):
        with ZipFile(document) as archive:
            return json.loads(archive.read('manifest.json'))['document']['layers']

    original = contents(template)
    results, product_blobs = [], []
    require(len(manifest['variants']) == 2, 'suite did not produce both editable variant documents')
    require(warnings == 0, 'short template text produced unexpected warnings')
    for row, variant in zip(rows, manifest['variants']):
        require(variant['name'] == row['name'], 'variant folder label did not follow CSV')
        require(len(variant['outputs']) == 6, 'variant did not produce six artboard files')
        sizes = sorted({(entry['artboard'], tuple(entry['pixels'])) for entry in variant['outputs']})
        require(sizes == sorted([('横版横幅', (960, 540)), ('竖版海报', (480, 640)), ('社媒方图', (640, 640))]),
                'variant did not preserve the three artboard sizes')
        require(all(entry['embedded_icc'].startswith('sRGB') for entry in variant['outputs']),
                'variant published an image without sRGB ICC')

        output = folder / variant['source']
        reopened = by_name(editor, output)
        updated = contents(output)
        require(len(original) == len(updated), 'template variant changed the number of top-level layers')
        replaced_sources = set()
        for before, after in zip(original, updated):
            left, right = before['content'], after['content']
            if not left.get('artboard'):
                continue
            require(left['artboard'] == right.get('artboard'), 'variant changed artboard geometry')
            require(len(left['children']) == len(right['children']), 'variant changed artboard layer structure')
            visible_layers = {layer['name']: layer for layer in reopened[before['name']]['children']}
            for prior, current in zip(left['children'], right['children']):
                name = prior['name']
                require(name == current['name'], 'variant changed template layer names or order')
                if name == '{{product}}':
                    require(visible_layers[name]['kind'] == 'Smart Object', 'variant flattened the product')
                    a, b = prior['content'], current['content']
                    require(a['transform'] == b['transform'], 'variant changed the product transform')
                    require(b['source']['kind'] == 'embedded', 'variant linked the product to a temporary file')
                    replaced_sources.add(b['source']['blob'])
                elif name in ('{{title}}', '{{detail}}'):
                    text = visible_layers[name]
                    require(text['kind'] == 'Type' and text['text']['text'] == row[name[2:-2]],
                            'variant did not save the exact CSV text as editable text')
                    a, b = prior['content'], current['content']
                    require(a['transform'] == b['transform'] and a['shape'] == b['shape'],
                            'variant changed a text box position or dimensions')
                else:
                    require(prior == current, 'variant changed an unbound design layer')
        require(len(replaced_sources) == 1, 'three identical-size image slots carry different embedded content')
        product_blobs.extend(replaced_sources)
        png = next(entry for entry in variant['outputs'] if entry['artboard'] == '竖版海报' and entry['format'] == 'png')
        results.append({'name': row['name'], 'artboards': dict(sizes), 'images': len(variant['outputs']),
                        'product_pixel': editor.pixel(folder / png['file'], 111, 406)})

    require(len(set(product_blobs)) == 2 and results[0]['product_pixel'] != results[1]['product_pixel'],
            'different images did not appear on the published artboard')
    require(template.read_bytes() == original_bytes, 'template batch modified the supplied source work')

    overflow = staging / '超出文本框.csv'
    bad_data = staging / '损坏图片.csv'
    broken = staging / '损坏图片.png'
    broken.write_bytes(b'invalid image')
    for path, table in [
        (overflow, [['偏长的标题', '一个非常长的标题，' * 6, '', ROOT / 'templates' / '海蓝款.png']]),
        (bad_data, [['正常组', '这是测试', '', ROOT / 'templates' / '海蓝款.png'], ['损坏组', '损坏素材', '', broken]]),
    ]:
        with path.open('w', encoding='utf-8-sig', newline='') as output:
            csv.writer(output).writerows([['name', 'title', 'detail', 'product'], *table])
    warning_folder, count = deliver_template(editor, template, overflow, target, formats[:1], 'cover')
    warning_manifest = json.loads((warning_folder / '套版清单.json').read_text(encoding='utf-8'))
    require(count >= 3 and any('空间不足' in w['message'] for w in warning_manifest['variants'][0]['warnings']),
            'long title was truncated without a warning')
    try:
        deliver_template(editor, template, bad_data, target, formats[:1], 'contain')
    except RuntimeError as error:
        require('第 3 行' in str(error), 'invalid asset error did not identify its CSV row')
    else:
        raise RuntimeError('template suite accepted an unreadable replacement')
    require(set(target.iterdir()) == {folder, warning_folder}, 'failed suite left behind a partial delivery')

    shared = staging / '共享占位.pcraft'
    editor.edit(template, [
        ('layer.select', {'layer': '{{product}}'}),
        ('layer.duplicate', {}),
        ('layer.setProps', {'name': '固定装饰'}),
    ], shared)
    try:
        template_slots(shared)
    except ValueError as error:
        require('共享' in str(error), 'mismatched binding rejected for an unrelated reason')
    else:
        raise RuntimeError('template suite could implicitly replace an unbound shared smart object')
    return {'variants': results, 'embedded_srgb': True, 'layer_geometry_preserved': True,
            'text_overflow_reported': True, 'partial_delivery_cleanup': True, 'shared_binding_validated': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('cli', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--font-family', help='Verify an installed font by its family name in the editor.')
    arguments = parser.parse_args()
    editor = Editor(arguments.cli.resolve())
    with tempfile.TemporaryDirectory(prefix='layerlight-verify-') as folder:
        staging = Path(folder)
        checks = {'engine': editor.version, 'psd': psd(editor, staging), 'complex_psd': complex_psd(editor, staging),
                  'retouch': retouch(editor, staging), 'content_aware_fill': content_aware_fill(editor, staging),
                  'remove_tool': remove_tool(editor, staging), 'edge_refinement': edge_refinement(editor, staging),
                  'artboards': artboards(editor, staging),
                  'batch_delivery': batch_delivery(editor, staging), 'asset_delivery': asset_delivery(editor, staging),
                  'template_delivery': template_delivery(editor, staging),
                  'font_report': font_report(editor, staging), 'linked_handoff': linked_handoff(editor, staging)}
        if arguments.font_family:
            checks['local_font'] = local_font(editor, staging, arguments.font_family)
    result = json.dumps(checks, ensure_ascii=False, indent=2) + '\n'
    if arguments.report:
        arguments.report.write_text(result, encoding='utf-8')
    print(result, end='')


if __name__ == '__main__':
    main()
