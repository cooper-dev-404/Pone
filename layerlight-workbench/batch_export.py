#!/usr/bin/env python3
"""Export design documents and assets using the native PhotoCraft image engine."""
import argparse
from datetime import datetime
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import unicodedata

from editor import Editor, VERSION


ROOT = Path(__file__).resolve().parent
FORMATS = {'png', 'jpg', 'webp'}
SOURCE_TYPES = {'.psd', '.psb', '.pcraft', '.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'}
SRGB = ('edit.convertToProfile', {'profile': 'srgb'})
MAX_DIMENSION = 300_000  # PhotoCraft's canvas dimension limit.


def state_path():
    override = os.environ.get('LAYERLIGHT_HOME')
    if override:
        return Path(override).expanduser()
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Layerlight Workbench'
    return Path.home() / '.local' / 'share' / 'layerlight-workbench'


def cli_path():
    override = os.environ.get('LAYERLIGHT_CLI')
    if override:
        return Path(override).expanduser()
    return state_path() / 'runtimes' / VERSION / 'PhotoCraft.app' / 'Contents' / 'MacOS' / 'photocraft-cli'


def component(name):
    normalized = unicodedata.normalize('NFC', name)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', normalized).strip(' .-')
    return text.encode('utf-8')[:96].decode('utf-8', errors='ignore').rstrip(' .-') or '未命名'


def bounded_int(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} 必须是 {low} 到 {high} 的整数。')
    return value


def encoding(spec):
    format_name = spec.get('format')
    if not isinstance(format_name, str) or format_name not in FORMATS:
        raise ValueError('输出格式须为 png、jpg 或 webp。')
    quality = spec.get('quality', 90 if format_name == 'jpg' else None)
    if quality is not None:
        if format_name == 'png':
            raise ValueError('PNG 使用无损编码，预设的 quality 仅适用于 JPG 和 WebP。')
        bounded_int(quality, 1, 100, 'quality')
    return format_name, quality


def load_recipe(path):
    raw = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(raw, dict) or set(raw) != {'version', 'variants', 'artboard_formats'}
            or type(raw['version']) is not int or raw['version'] != 1):
        raise ValueError('预设需包含 version: 1、variants 和 artboard_formats。')

    variants = []
    used_names = set()
    if not isinstance(raw['variants'], list) or not raw['variants']:
        raise ValueError('需要至少一个单画布尺寸预设。')
    for spec in raw['variants']:
        if not isinstance(spec, dict) or set(spec) - {'name', 'width', 'height', 'fit', 'format', 'quality'}:
            raise ValueError('尺寸预设包含未知字段。')
        name = spec.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('每条尺寸预设需要 name。')
        name = component(name)
        if name.casefold() in used_names:
            raise ValueError(f'尺寸预设名称有重复：{name}')
        used_names.add(name.casefold())
        fit = spec.get('fit')
        if fit not in ('contain', 'cover'):
            raise ValueError(f'{name} 的 fit 须为 contain 或 cover。')
        width = bounded_int(spec.get('width'), 1, MAX_DIMENSION, f'{name} 宽度')
        height = bounded_int(spec.get('height'), 1, MAX_DIMENSION, f'{name} 高度')
        variants.append((name, width, height, fit, encoding(spec)))

    formats = []
    if not isinstance(raw['artboard_formats'], list) or not raw['artboard_formats']:
        raise ValueError('需要至少一种画板输出格式。')
    for spec in raw['artboard_formats']:
        if not isinstance(spec, dict) or set(spec) - {'format', 'quality'}:
            raise ValueError('画板格式包含未知字段。')
        formats.append(encoding(spec))
    if len({format_name for format_name, _ in formats}) != len(formats):
        raise ValueError('画板输出格式有重复。')
    return variants, formats


def resized(source_w, source_h, target_w, target_h, fit):
    if fit == 'cover':
        crop_w = min(source_w, max(1, round(Fraction(source_h * target_w, target_h))))
        crop_h = min(source_h, max(1, round(Fraction(source_w * target_h, target_w))))
        return [('image.crop', {
            'x': (source_w - crop_w) // 2, 'y': (source_h - crop_h) // 2,
            'width': crop_w, 'height': crop_h, 'targetWidth': target_w, 'targetHeight': target_h,
            'resample': 'lanczos',
        })]

    scale = min(Fraction(target_w, source_w), Fraction(target_h, source_h))
    width, height = max(1, round(source_w * scale)), max(1, round(source_h * scale))
    steps = [('image.imageSize', {'width': width, 'height': height, 'resample': 'lanczos'})]
    if (width, height) != (target_w, target_h):
        steps.append(('image.canvasSize', {
            'width': target_w, 'height': target_h, 'anchor': 'center', 'extensionColor': 'transparent',
        }))
    return steps


def render(editor, source, target, quality, steps):
    options = ['--metadata', 'none']
    if quality is not None:
        options.extend(['--quality', str(quality)])
    editor.edit(source, steps, target, options=options)


def file_entry(editor, output_root, file, width, height, **details):
    geometry, color = editor.edit(file, [('document.inspect', {}), ('edit.profileInfo', {})])
    actual = [geometry['result']['width'], geometry['result']['height']]
    if actual != [width, height]:
        raise RuntimeError(f'{file.name} 的实际尺寸 {actual} 与要求 {[width, height]} 不符。')
    icc = color['result']
    expected = next(profile['description'] for profile in icc['builtins'] if profile['id'] == 'srgb')
    profile = icc['profile']
    if profile['description'] != expected or not profile['embedded']:
        raise RuntimeError(f'{file.name} 没有嵌入预期的 sRGB 色彩配置。')
    return {
        'file': file.relative_to(output_root).as_posix(), 'pixels': actual, 'bytes': file.stat().st_size,
        'format': file.suffix.removeprefix('.'), 'embedded_icc': profile['description'], **details,
    }


def run_variants(editor, source, size, variants, stage, folder):
    entries = []
    for name, width, height, fit, (format_name, quality) in variants:
        output = folder / f'{name}-{width}x{height}.{format_name}'
        steps = [SRGB, *resized(*size, width, height, fit)]
        render(editor, source, output, quality, steps)
        entries.append(file_entry(editor, stage, output, width, height, variant=name, fit=fit))
    return entries


def run_artboards(editor, source, artboards, formats, stage, folder, scratch):
    entries = []
    for index, layer in enumerate(artboards, 1):
        name = component(layer['name'])
        width, height = layer['artboard']['rect'][2:4]
        [export] = editor.edit(source, [
            ('file.export.artboardsToFiles', {
                'dir': str(scratch), 'format': 'png', 'prefix': f'board-{index:03d}',
                'artboards': [layer['id']],
            }),
        ])
        files = export.get('result', {}).get('files')
        if not isinstance(files, list) or len(files) != 1:
            raise RuntimeError(f'画板 {name} 未导出为单张图片。')
        original = Path(files[0]).resolve(strict=True)
        if original.parent != scratch or original.suffix != '.png':
            raise RuntimeError(f'画板 {name} 的中间文件路径不符合预期。')
        for format_name, quality in formats:
            output = folder / f'{index:03d}-{name}-{width}x{height}.{format_name}'
            render(editor, original, output, quality, [SRGB])
            entries.append(file_entry(editor, stage, output, width, height, artboard=layer['name']))
        original.unlink()
    return entries


def asset_scales(value):
    scales = []
    for raw in value.split(','):
        token = raw.strip()
        if not re.fullmatch(r'[0-9]{1,2}(?:\.[0-9]{1,2})?', token):
            raise argparse.ArgumentTypeError('请用逗号分隔倍率，例如 1,1.5,2。')
        scale = Fraction(token)
        if not Fraction(1, 4) <= scale <= 10 or scale in scales:
            raise argparse.ArgumentTypeError('倍率需介于 0.25 和 10 之间，且不能重复。')
        scales.append(scale)
    return scales


def tagged_layers(layers, parents=()):
    for layer in layers:
        if not layer['visible']:
            continue
        path = (*parents, layer['name'])
        match = re.fullmatch(r'导出[:：]\s*(.*)', layer['name'], flags=re.DOTALL)
        if match:
            name = match[1].strip()
            if not name or layer['kind'] == 'Adjustment':
                raise ValueError(f'请给有图像内容的导出图层命名：{" / ".join(path)}')
            yield name, layer['id'], path
        yield from tagged_layers(layer.get('children', []), path)


def write_asset(editor, source, stem, base_size, formats, scales, stage, *, crop=None, **details):
    entries = []
    for scale in scales:
        width, height = (max(1, int(side * scale + Fraction(1, 2))) for side in base_size)
        if max(width, height) > MAX_DIMENSION:
            raise ValueError(f'{stem.name} 的输出尺寸超出编辑器上限，请降低倍率。')
        steps = []
        if crop:
            x, y, w, h = crop
            steps.append(('image.crop', {
                'x': x, 'y': y, 'width': w, 'height': h,
                'targetWidth': width, 'targetHeight': height, 'resample': 'lanczos',
            }))
        elif (width, height) != base_size:
            steps.append(('image.imageSize', {'width': width, 'height': height, 'resample': 'lanczos'}))
        steps.append(SRGB)
        label = f'{float(scale):g}x'
        for format_name, quality in formats:
            output = stem.with_name(f'{stem.name}@{label}.{format_name}')
            render(editor, source, output, quality, steps)
            entries.append(file_entry(editor, stage, output, width, height, scale=float(scale), **details))
    return entries


def run_assets(editor, source, info, stage, folder, scratch, mode, options):
    formats, scales, prefix = options
    layers = list(tagged_layers(info['layers'])) if mode in ('layers', 'assets') else []
    slices = []
    if mode in ('slices', 'assets'):
        [reply] = editor.edit(source, [('slice.list', {})])
        slices = [item for item in reply['result']['slices']
                  if item['origin'] != 'auto' and item['kind'] == 'image' and min(item['rect'][2:]) > 0]
    if not layers and not slices:
        raise ValueError(f'{source.name} 没有可导出的素材。请检查「导出:」图层标记或已保存的图像切片。')

    outputs = []
    if layers:
        layer_folder = folder / '图层'
        layer_folder.mkdir()
        intermediate = scratch / 'layer.tif'
        for index, (name, layer_id, path) in enumerate(layers, 1):
            try:
                [export] = editor.edit(source, [('layer.exportAs', {'layer': layer_id, 'path': str(intermediate)})])
            except RuntimeError as error:
                raise RuntimeError(f'无法导出图层 {" / ".join(path)}。{error}') from error
            size = export['result']['width'], export['result']['height']
            stem = layer_folder / f'{index:03d}-{prefix}{component(name)}'
            outputs.extend(write_asset(editor, intermediate, stem, size, formats, scales, stage,
                                       name=name, kind='layer', layer_path=path, layer_id=layer_id))
            intermediate.unlink()
    if slices:
        slice_folder = folder / '切片'
        slice_folder.mkdir()
        composite = scratch / 'slices.tif'
        editor.call('convert', source, composite, '--tiff-transparency', 'on', '--metadata', 'none')
        for index, item in enumerate(slices, 1):
            rect = item['rect']
            name = item['name']
            stem = slice_folder / f'{index:03d}-{prefix}{component(name)}'
            outputs.extend(write_asset(editor, composite, stem, tuple(rect[2:]), formats, scales, stage,
                                       crop=rect, name=name, kind='slice', slice_id=item['id'], rect=rect))
        composite.unlink()
    return outputs


def sources_from(paths):
    sources = []
    seen = set()
    for arg in paths:
        source = arg.expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in SOURCE_TYPES:
            raise ValueError(f'无法交付此输入文件：{arg}')
        if source in seen:
            raise ValueError(f'重复的输入文件：{arg}')
        sources.append(source)
        seen.add(source)
    return sources


def source_revision(source):
    info = source.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def deliver(editor, sources, variants, formats, destination, *, mode='document', scales=(1, 2), prefix=''):
    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve(strict=True)
    run_name = '交付-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(8)
    final = destination / run_name
    revisions = {source: source_revision(source) for source in sources}

    # Publish a complete set with one rename after every output has decoded and passed its size check.
    with tempfile.TemporaryDirectory(prefix='.layerlight-', dir=destination) as temporary:
        working = Path(temporary)
        stage = working / 'delivery'
        stage.mkdir()
        scratch = working / 'artboards'
        scratch.mkdir()
        documents = []
        for index, source in enumerate(sources, 1):
            info = editor.info(source)
            boards = [layer for layer in info['layers'] if layer.get('artboard')]
            folder = stage / f'{index:03d}-{component(source.stem)}'
            folder.mkdir()
            size = info['width'], info['height']
            if mode != 'document':
                options = formats, scales, f'{component(prefix)}-' if prefix else ''
                outputs = run_assets(editor, source, info, stage, folder, scratch, mode, options)
            elif boards:
                outputs = run_artboards(editor, source, boards, formats, stage, folder, scratch)
            else:
                # Composite in the document's original color space, retaining alpha before sRGB
                # conversion. Photoshop-style Flatten Image would composite on white.
                composite = scratch / f'source-{index:03d}.tif'
                editor.call('convert', source, composite, '--tiff-transparency', 'on', '--metadata', 'none')
                outputs = run_variants(editor, composite, size, variants, stage, folder)
                composite.unlink()
            documents.append({'source': source.name, 'source_pixels': size, 'outputs': outputs})

        for source, expected in revisions.items():
            if source_revision(source) != expected:
                raise RuntimeError(f'{source.name} 在出图时发生变化，请保存稿件后重新出图。')
        manifest = {'version': 1, 'engine': editor.version, 'color_space': 'sRGB', 'documents': documents}
        if mode != 'document':
            manifest['mode'] = mode
        (stage / '交付清单.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        if final.exists():
            raise FileExistsError(f'交付目录已存在：{final}')
        stage.rename(final)
    return final


def main():
    parser = argparse.ArgumentParser(description='将设计稿、画板、图层或切片批量交付为 sRGB 位图。')
    parser.add_argument('source', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, default=state_path() / 'Exports', help='交付目录，每次运行新建一份。')
    parser.add_argument('--recipe', type=Path, default=ROOT / 'batch_recipe.json')
    parser.add_argument('--mode', choices=('document', 'layers', 'slices', 'assets'), default='document',
                        help='选择整稿与画板、标记图层、图像切片，或同时导出图层与切片。')
    parser.add_argument('--scales', type=asset_scales, help='素材倍率，以逗号分隔。默认 1,2。')
    parser.add_argument('--prefix', help='图层与切片成品的文件名前缀。')
    parser.add_argument('--cli', type=Path, default=cli_path(), help='PhotoCraft CLI 的路径。')
    args = parser.parse_args()

    try:
        binary = args.cli.expanduser().resolve()
        if not binary.is_file():
            raise ValueError('找不到 PhotoCraft CLI。请先运行 P一下.command 安装工作台。')
        variants, formats = load_recipe(args.recipe.expanduser())
        sources = sources_from(args.source)
        if args.mode == 'document' and (args.scales or args.prefix):
            raise ValueError('--scales 和 --prefix 用于图层或切片模式。')
        final = deliver(Editor(binary), sources, variants, formats, args.output.expanduser(),
                        mode=args.mode, scales=args.scales or (1, 2), prefix=args.prefix or '')
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'交付失败：{error}\n')
    print(final)


if __name__ == '__main__':
    main()
