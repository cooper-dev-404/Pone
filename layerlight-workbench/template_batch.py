#!/usr/bin/env python3
"""Populate editable, artboard-based PhotoCraft templates from a UTF-8 CSV."""
import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
import zipfile

from batch_export import (
    cli_path, component, load_recipe, render, resized, run_artboards, source_revision, state_path,
)
from editor import Editor


ROOT = Path(__file__).resolve().parent
SLOT = re.compile(r'\{\{([^\W\d]\w{0,63})\}\}')
IMAGE_TYPES = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}


def template_slots(template):
    # CLI layer information omits the contents ID that independent/shared smart objects use.
    with zipfile.ZipFile(template) as bundle:
        layers = json.loads(bundle.read('manifest.json'))['document']['layers']

    slots = {}
    smart_instances = {}
    boards = {}

    def visit(items, parent_board=None):
        for layer in items:
            content = layer['content']
            name, layer_id, kind = layer['name'], layer['id'], content['kind']
            board = parent_board
            if content.get('artboard'):
                board = layer_id
                boards[board] = name

            match = SLOT.fullmatch(name)
            field = match[1] if match else None
            if kind == 'smart':
                smart_instances.setdefault(content['contents_id'], []).append(field)
            if field:
                if field == 'name':
                    raise ValueError('{{name}} 已保留给交付目录名。请为图层使用其他字段。')
                if board is None or kind not in ('text', 'smart'):
                    raise ValueError(f'{name} 必须是画板中的文字图层或嵌入式智能对象。')
                if kind == 'smart' and content['source']['kind'] != 'embedded':
                    raise ValueError(f'{name} 使用了链接素材。请将智能对象转换为嵌入式。')
                slot = slots.setdefault(field, {'kind': kind, 'layers': []})
                if slot['kind'] != kind:
                    raise ValueError(f'{name} 同时用于文字和图片。请将它们改成不同的字段名。')
                slot['layers'].append((layer_id, board, content.get('contents_id')))
            visit(content.get('children', []), board)

    visit(layers)
    if not boards or not slots:
        raise ValueError('模板需要至少一个画板，以及一个以 {{字段}} 命名的可替换图层。')
    for field, slot in slots.items():
        if slot['kind'] == 'smart':
            for _, _, contents_id in slot['layers']:
                if set(smart_instances[contents_id]) != {field}:
                    raise ValueError(
                        f'{{{{{field}}}}} 与别的图层共享智能对象内容。请使用相同的占位名，'
                        '或通过「通过拷贝新建智能对象」创建独立图层。'
                    )
    return slots


def read_rows(csv_path, slots, revisions):
    rows, used_names = [], set()
    with csv_path.open(encoding='utf-8-sig', newline='') as source:
        reader = csv.reader(source, strict=True)
        header = next(reader, [])
        expected = {'name', *slots}
        if len(header) != len(expected) or set(header) != expected:
            raise ValueError(f'CSV 首行需包含 {", ".join(sorted(expected))}，顺序不限。')
        for cells in reader:
            if not cells:
                continue
            line = reader.line_num
            if len(cells) != len(header):
                raise ValueError(f'CSV 第 {line} 行的列数与首行不一致。')
            values = dict(zip(header, cells))
            name = values.pop('name').strip()
            normalized = component(name).casefold()
            if not name or normalized in used_names:
                raise ValueError(f'CSV 第 {line} 行的 name 为空或与前面的名称重复。')
            used_names.add(normalized)
            for field, slot in slots.items():
                value = values[field]
                if '\0' in value:
                    raise ValueError(f'CSV 第 {line} 行的 {field} 含无效字符。')
                if slot['kind'] == 'smart':
                    candidate = csv_path.parent / Path(value.strip()).expanduser()
                    if candidate.suffix.lower() not in IMAGE_TYPES or not candidate.is_file():
                        raise ValueError(f'CSV 第 {line} 行的 {field} 图片无效或找不到　{value}')
                    path = candidate.resolve(strict=True)
                    if path not in revisions:
                        revisions[path] = source_revision(path)
                    values[field] = path
            rows.append((name, line, values))
    if not rows:
        raise ValueError('CSV 至少需要一组内容。')
    return rows


def image_slots(editor, template, slots):
    discovered = {}
    for field, slot in slots.items():
        if slot['kind'] != 'smart':
            continue
        for layer, _, contents_id in slot['layers']:
            if contents_id not in discovered:
                results = editor.edit(template, [
                    ('layer.select', {'layer': layer}),
                    ('layer.smartObjects.editContents', {'layer': layer}),
                    ('document.inspect', {}),
                ])
                size = results[-1]['result']
                discovered[contents_id] = (field, layer, (size['width'], size['height']))
    return list(discovered.values())


def populate(editor, template, output, values, slots, image_bindings, artboards, fit, scratch, normalized):
    commands = []
    for field, layer, size in image_bindings:
        asset = values[field]
        key = asset, size
        if key not in normalized:
            [result] = editor.edit(asset, [('document.inspect', {})])
            source = result['result']
            plate_folder = scratch / f'asset-{len(normalized) + 1:04d}'
            plate_folder.mkdir()
            plate = plate_folder / f'{component(asset.stem)}.png'
            render(editor, asset, plate, None, resized(source['width'], source['height'], *size, fit))
            normalized[key] = plate
        commands.extend([
            ('layer.select', {'layer': layer}),
            ('layer.smartObjects.replaceContents', {'layer': layer, 'path': str(normalized[key])}),
        ])

    text_boards = {}
    for field, slot in slots.items():
        if slot['kind'] == 'text':
            for layer, board, _ in slot['layers']:
                commands.extend([
                    ('type.edit', {'layer': layer, 'text': values[field], 'name': '{{' + field + '}}'}),
                    ('type.info', {'layer': layer}),
                ])
                text_boards[layer] = (field, board)

    warnings = []
    for (command, _), response in zip(commands, editor.edit(template, commands, output)):
        details = response['result']
        if command == 'layer.smartObjects.replaceContents':
            warnings.extend({'layer': details['layer'], 'message': message} for message in details['warnings'])
        if command == 'type.info':
            layer = details['layer']
            field, board = text_boards[layer]
            name, (x, y, w, h) = artboards[board]
            messages = list(details.get('warnings', []))
            if 'Box' in details['shape']:
                end = max((line['end'] for line in details['lines']), default=0)
                if details['text'][end:].strip():
                    messages.append('文字排版框的空间不足，部分内容未显示。')
            if details['bounds'] and details['text'].strip():
                left, top, right, bottom = details['bounds']
                if right > left and bottom > top and (left < x or top < y or right > x + w or bottom > y + h):
                    messages.append('文字可见范围超出画板。')
            warnings.extend({'layer': layer, 'field': field, 'artboard': name, 'message': m} for m in messages)
    return warnings


def deliver(editor, template, csv_path, destination, formats, fit):
    revisions = {path: source_revision(path) for path in (template, csv_path)}
    slots = template_slots(template)
    rows = read_rows(csv_path, slots, revisions)
    boards = [layer for layer in editor.info(template)['layers'] if layer.get('artboard')]
    artboards = {layer['id']: (layer['name'], layer['artboard']['rect']) for layer in boards}
    if not artboards or any(board not in artboards for slot in slots.values() for _, board, _ in slot['layers']):
        raise ValueError('请将画板放在文档顶层。')
    image_bindings = image_slots(editor, template, slots)

    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve(strict=True)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    final = destination / f'套版-{timestamp}-{secrets.token_hex(8)}'
    with tempfile.TemporaryDirectory(prefix='.layerlight-', dir=destination) as temporary:
        stage, scratch = Path(temporary) / 'delivery', Path(temporary) / 'scratch'
        stage.mkdir()
        scratch.mkdir()
        variants, normalized = [], {}
        for index, (name, line, values) in enumerate(rows, 1):
            folder = stage / f'{index:03d}-{component(name)}'
            images = folder / '发布图'
            images.mkdir(parents=True)
            source = folder / '源稿.pcraft'
            try:
                warnings = populate(
                    editor, template, source, values, slots, image_bindings, artboards, fit, scratch, normalized,
                )
                outputs = run_artboards(editor, source, boards, formats, stage, images, scratch)
            except (OSError, RuntimeError, ValueError) as error:
                raise RuntimeError(f'CSV 第 {line} 行（{name}）处理失败　{error}') from error
            variants.append({
                'name': name, 'csv_line': line, 'source': source.relative_to(stage).as_posix(),
                'outputs': outputs, 'warnings': warnings,
            })
        for path, before in revisions.items():
            if source_revision(path) != before:
                raise RuntimeError(f'{path.name} 在套版期间发生变动。请保存后重试。')
        manifest = {
            'version': 1, 'engine': editor.version, 'template': template.name, 'csv': csv_path.name,
            'image_fit': fit, 'color_space': 'sRGB', 'variants': variants,
        }
        (stage / '套版清单.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if final.exists():
            raise FileExistsError(f'套版目录已存在　{final}')
        stage.rename(final)
    return final, sum(len(variant['warnings']) for variant in variants)


def main():
    parser = argparse.ArgumentParser(description='按 CSV 批量替换画板中的文字和智能对象，并交付可编辑源稿与发布图。')
    parser.add_argument('template', type=Path, help='包含 {{字段}} 占位图层的 .pcraft 模板。')
    parser.add_argument('csv', type=Path, help='UTF-8 编码的 CSV 数据表。')
    parser.add_argument('--output', type=Path, default=state_path() / 'Exports')
    parser.add_argument('--fit', choices=('contain', 'cover'), default='contain', help='图片等比留边或居中裁切。')
    parser.add_argument('--recipe', type=Path, default=ROOT / 'batch_recipe.json', help='复用批量出图预设的画板格式。')
    parser.add_argument('--cli', type=Path, default=cli_path())
    args = parser.parse_args()
    try:
        binary = args.cli.expanduser().resolve()
        if not binary.is_file():
            raise ValueError('找不到 PhotoCraft CLI。请先运行 P一下.command 安装工作台。')
        template = args.template.expanduser().resolve(strict=True)
        csv_path = args.csv.expanduser().resolve(strict=True)
        if template.suffix.lower() != '.pcraft':
            raise ValueError('请先将模板另存为 PhotoCraft 文档（.pcraft）。')
        _, formats = load_recipe(args.recipe.expanduser())
        final, warnings = deliver(Editor(binary), template, csv_path, args.output.expanduser(), formats, args.fit)
    except (OSError, RuntimeError, ValueError, KeyError, csv.Error, zipfile.BadZipFile) as error:
        parser.exit(1, f'套版失败：{error}\n')
    if warnings:
        print(f'套版完成，有 {warnings} 条提示。详情见套版清单。', file=sys.stderr)
    print(final)


if __name__ == '__main__':
    main()
