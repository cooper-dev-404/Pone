#!/usr/bin/env python3
"""Inspect linked smart objects and build movable PhotoCraft packages."""
import argparse
from datetime import datetime
from html import escape
import json
from pathlib import Path
import secrets
import tempfile

from batch_export import cli_path, component, source_revision, state_path
from editor import Editor
from font_check import DOCUMENT_TYPES, STYLE


RELINK = 'layer.smartObjects.relinkToFile'


def linked_layers(layers, parents=()):
    for layer in layers:
        label = (layer['name'] or '未命名') + ('（画板）' if layer.get('artboard') else '')
        path = (*parents, label)
        source = layer.get('smartSource', {})
        if source.get('kind') == 'linked':
            yield {'layer': layer['id'], 'layer_path': path,
                   'contents': layer['smartContents']['id'], 'path': source['path']}
        yield from linked_layers(layer.get('children', []), path)


def inspect_links(editor, document):
    revision = source_revision(document)
    assets = {}
    for layer in linked_layers(editor.info(document)['layers']):
        assets.setdefault(layer['path'], []).append(layer)
    result = []
    for path, layers in assets.items():
        layer = layers[0]['layer']
        issue = ''
        try:
            editor.edit(document, [('layer.select', {'layer': layer}),
                                   ('layer.smartObjects.editContents', {'layer': layer})])
        except RuntimeError as error:
            issue = str(error)
        result.append({'path': path, 'layers': layers, 'issue': issue})
    if source_revision(document) != revision:
        raise RuntimeError('检查期间源稿发生变化，请保存后重试。')
    return result


def write_report(editor, source, destination):
    assets = inspect_links(editor, source)
    rows = []
    for asset in assets:
        path = escape(asset['path'])
        placements = '<br>'.join(escape(' › '.join(layer['layer_path'])) + f" <small>#{layer['layer']}</small>"
                                 for layer in asset['layers'])
        issue = asset['issue']
        status = ('无法读取<details><summary>详情</summary><pre>' + escape(issue) + '</pre></details>') if issue else '可读取'
        rows.append(f'<tr><td>{path}</td><td>{placements}</td><td>{status}</td></tr>')
    broken = sum(bool(asset['issue']) for asset in assets)
    count = sum(len(asset['layers']) for asset in assets)
    table = ('<section><table><thead><tr><th scope="col">原链接</th><th scope="col">图层位置</th>'
             '<th scope="col">读取状态</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></section>') if rows else ''
    report = f'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>链接素材检查 · P一下</title><style>{STYLE}</style></head>
<body><main>
<h1>链接素材检查</h1>
<p>{escape(source.name)} 有 {len(assets)} 个链接来源，涉及 {count} 个图层。{broken} 个来源无法读取。</p>
{table}
<footer><p>可在编辑器的「图层 → 智能对象」菜单中重新链接到文件。引用同一智能对象内容的实例会一起更新。</p></footer>
</main></body></html>
'''
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.layerlight-', dir=destination) as staging:
        draft = Path(staging) / 'report.html'
        draft.write_text(report, encoding='utf-8')
        output = destination / f'链接检查-{component(source.stem)}-{secrets.token_hex(8)}.html'
        draft.rename(output)
    return output


def relink_steps(layers, replacements):
    by_id = {layer['layer']: layer for layer in layers}
    seen = set()
    steps = []
    for layer_id, path in replacements:
        layer = by_id.get(layer_id)
        if not layer:
            raise ValueError(f'图层 #{layer_id} 不是当前源稿里的链接智能对象。')
        if layer['contents'] in seen:
            raise ValueError(f'图层 #{layer_id} 与另一指定图层共享内容。请只为其中一个提供新路径。')
        seen.add(layer['contents'])
        steps.extend([('layer.select', {'layer': layer_id}), (RELINK, {'layer': layer_id, 'path': path})])
    return steps


def portable_links(editor, document, copied):
    layers = list(linked_layers(editor.info(document)['layers']))
    links_dir = document.parent / 'Links'
    expected = set(copied)
    if any(path.parent != links_dir or not path.is_file() for path in expected):
        raise RuntimeError('编辑引擎返回的素材文件与包目录不一致。')
    # A placed native document with external links still depends on its own folder structure.
    for path in expected:
        if path.suffix.lower() in DOCUMENT_TYPES and any(linked_layers(editor.info(path)['layers'])):
            raise RuntimeError(f'素材 {path.name} 本身包含外部链接，请先将其内部链接嵌入后再打包。')

    replacements = {}
    placements = {}
    for layer in layers:
        current = Path(layer['path'])
        if current not in expected:
            raise RuntimeError(f'图层 #{layer["layer"]} 的链接未复制到交接包。')
        relative = current.relative_to(document.parent).as_posix()
        placements[layer['layer']] = (layer['contents'], relative)
        replacements.setdefault(layer['contents'], (layer['layer'], relative))
    if {Path(layer['path']) for layer in layers} != expected:
        raise RuntimeError('复制的素材与文档内的链接不一致。')
    if replacements:
        updated = document.with_name(f'.portable-{secrets.token_hex(8)}.pcraft')
        editor.edit(document, relink_steps(layers, replacements.values()), updated)
        updated.replace(document)

    final = list(linked_layers(editor.info(document)['layers']))
    manifest = {path.relative_to(document.parent).as_posix(): [] for path in copied}
    if {layer['layer']: (layer['contents'], layer['path']) for layer in final} != placements:
        raise RuntimeError('重新链接后的图层引用与预期的包内相对路径不一致。')
    for layer in final:
        path = layer.pop('path')
        if path not in manifest:
            raise RuntimeError(f'图层 #{layer["layer"]} 的链接未保存为包内相对路径。')
        manifest[path].append(layer)
    if not all(manifest.values()):
        raise RuntimeError('交接包中出现未引用的素材。')
    return [{'file': name, 'layers': refs} for name, refs in manifest.items()]


def package(editor, source, destination, replacements=()):
    revision = source_revision(source)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    final = destination / f'{component(source.stem)}-交接-{stamp}-{secrets.token_hex(8)}'
    with tempfile.TemporaryDirectory(prefix='.layerlight-', dir=destination) as staging:
        stage = Path(staging)
        steps = []
        if replacements:
            layers = linked_layers(editor.info(source)['layers'])
            steps = relink_steps(layers, replacements)
        responses = editor.edit(source, [*steps, ('file.package', {'dir': str(stage), 'format': 'pcraft'})])
        result = responses[-1]['result']
        if result['missing']:
            missing = '\n'.join(result['missing'])
            raise RuntimeError(f'请先重新链接这些素材，再打包。\n{missing}')
        document, folder = Path(result['document']), Path(result['folder'])
        if folder.parent != stage or document.parent != folder or not document.is_file():
            raise RuntimeError('编辑引擎返回的稿件位置与包目录不一致。')
        assets = portable_links(editor, document, [Path(path) for path in result['links']])
        if source_revision(source) != revision:
            raise RuntimeError('打包期间源稿发生变化，请保存后重试。')
        warnings = list(dict.fromkeys(warning for response in responses
                                      for warning in (response['result'] or {}).get('warnings', [])))
        manifest = {'version': 1, 'engine': editor.version, 'document': document.name,
                    'links': assets, 'warnings': warnings}
        (folder / '链接清单.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        folder.rename(final)
    return final


def main():
    parser = argparse.ArgumentParser(description='检查已保存稿件的链接素材，或生成可搬移的 .pcraft 交接包。')
    parser.add_argument('action', choices=('check', 'package'))
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--relink', action='append', nargs=2, metavar=('LAYER_ID', 'FILE'), default=[],
                        help='打包时指定替换素材的图层编号和本地文件。可重复指定。')
    parser.add_argument('--cli', type=Path, default=cli_path())
    args = parser.parse_args()
    try:
        source = args.source.expanduser().resolve(strict=True)
        if source.suffix.lower() not in DOCUMENT_TYPES or not source.is_file():
            raise ValueError('请选择 PSD、PSB 或 .pcraft 源稿。')
        binary = args.cli.expanduser().resolve()
        if not binary.is_file():
            raise ValueError('找不到 PhotoCraft CLI。请先运行 P一下.command 安装工作台。')
        editor = Editor(binary)
        output = args.output or state_path() / ('Reports' if args.action == 'check' else 'Packages')
        output = output.expanduser().resolve()
        if args.action == 'check':
            if args.relink:
                raise ValueError('--relink 用于打包交接。')
            result = write_report(editor, source, output)
        else:
            replacements = []
            for layer_id, file in args.relink:
                path = Path(file).expanduser().resolve(strict=True)
                if not path.is_file():
                    raise ValueError(f'替换素材必须是文件　{path}')
                replacements.append((int(layer_id), str(path)))
            result = package(editor, source, output, replacements)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'链接素材处理失败　{error}\n')
    print(result)


if __name__ == '__main__':
    main()
