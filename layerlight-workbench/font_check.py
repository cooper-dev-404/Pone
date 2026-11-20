#!/usr/bin/env python3
"""Locate missing font families in editable text layers without saving the source."""
import argparse
from datetime import datetime
from html import escape
from pathlib import Path
import tempfile

from batch_export import cli_path, source_revision, state_path
from editor import Editor


DOCUMENT_TYPES = {'.psd', '.psb', '.pcraft'}
FONT_WARNING_START = "font '"
FONT_WARNING_END = "' is not installed; text may render using a fallback face"


def missing_families(warnings):
    # Match the pinned engine's missing-family diagnostic, including its PostScript alias lookup.
    return {
        warning[len(FONT_WARNING_START):-len(FONT_WARNING_END)]
        for warning in warnings
        if warning.startswith(FONT_WARNING_START) and warning.endswith(FONT_WARNING_END)
    }


def text_layers(layers, path=(), visible=True):
    for layer in layers:
        label = layer['name'] or '未命名'
        layer_path = (*path, label + ('（画板）' if layer.get('artboard') else ''))
        layer_visible = visible and layer['visible']
        if layer['kind'] == 'Type':
            yield layer, layer_path, layer_visible
        yield from text_layers(layer.get('children', []), layer_path, layer_visible)


def inspect_fonts(editor, source):
    revision = source_revision(source)
    document = editor.info(source)
    layers = list(text_layers(document['layers']))
    missing = missing_families(document['warnings'])
    candidates = [
        (layer, path, visible) for layer, path, visible in layers
        if any(run['style']['font_family'] in missing for run in layer['text']['runs'])
    ]
    affected = []
    # Limit argv size for deeply layered documents on macOS.
    for start in range(0, len(candidates), 250):
        batch = candidates[start:start + 250]
        results = editor.edit(source, [('type.info', {'layer': layer['id']}) for layer, _, _ in batch])
        if [reply['result']['layer'] for reply in results] != [layer['id'] for layer, _, _ in batch]:
            raise RuntimeError('编辑引擎返回的文字图层与源稿不一致。')
        for reply, (layer, path, visible) in zip(results, batch):
            families = missing_families(reply['result'].get('warnings', []))
            if families:
                affected.append((path, layer['id'], visible, sorted(families, key=str.casefold)))
    if source_revision(source) != revision:
        raise RuntimeError('检查期间源稿发生变化，请保存后重试。')
    located = {family for _, _, _, families in affected for family in families}
    return len(layers), affected, sorted(missing - located, key=str.casefold)


STYLE = """
* { box-sizing: border-box }
body { margin:0; background:#f0f4f3; color:#172723; font:15px/1.55 system-ui, 'PingFang SC', sans-serif }
main { max-width:1050px; margin:auto; padding:42px 24px }
h1 { margin:0 0 8px; font-size:34px; letter-spacing:-.03em }
h2 { margin:0; font-size:19px; overflow-wrap:anywhere }
p { margin:8px 0; overflow-wrap:anywhere }
.muted, footer { color:#52655e }
section { margin:18px 0; padding:20px 24px; border:1px solid #cad8d3; border-radius:12px; background:white }
section.issue { border-left:4px solid #ad661e }
table { width:100%; margin-top:14px; border-collapse:collapse }
th, td { padding:10px 12px; text-align:left; vertical-align:top; border-bottom:1px solid #dfe8e4; overflow-wrap:anywhere }
th { background:#e8f0ed; color:#334e44 }
.status { white-space:nowrap }
pre { white-space:pre-wrap; overflow-wrap:anywhere; margin-bottom:0 }
@media (max-width:600px) { main { padding:24px 12px } section { padding:14px } th,td { padding:8px } }
"""


def render_report(editor, sources):
    sections, affected_total, failed_total = [], 0, 0
    for source in sources:
        heading = f'<h2>{escape(source.name)}</h2><p class="muted">{escape(str(source.parent))}</p>'
        try:
            count, affected, unlocated = inspect_fonts(editor, source)
        except (OSError, RuntimeError, ValueError) as error:
            failed_total += 1
            sections.append(f'<section class="issue">{heading}<p>无法检查</p><pre>{escape(str(error))}</pre></section>')
            continue
        affected_total += len(affected)
        rows = []
        for path, layer_id, visible, families in affected:
            location = escape(' › '.join(path))
            fonts = '<br>'.join(map(escape, families))
            visibility = '可见' if visible else '隐藏'
            rows.append(f'<tr><td>{location}<br><small class="muted">图层 #{layer_id}</small></td>'
                        f'<td>{fonts}</td><td class="status">{visibility}</td></tr>')
        table = ''
        if rows:
            table = ('<table><thead><tr><th scope="col">图层位置</th><th scope="col">缺失字体</th>'
                     '<th scope="col">图层显隐</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')
        extra = f'<p>引擎另报出未定位的缺失字体　{escape("、".join(unlocated))}</p>' if unlocated else ''
        flagged = ' class="issue"' if rows or unlocated else ''
        sections.append(f'<section{flagged}>{heading}<p>检查 {count} 个文字图层，{len(affected)} 个缺字体。</p>'
                        f'{table}{extra}</section>')

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>字体交接检查 · P一下</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>字体交接检查</h1>
<p>共 {len(sources)} 份稿件，{affected_total} 个文字图层缺字体，{failed_total} 份稿件无法检查。</p>
{''.join(sections)}
<footer>
<p>检查范围为主文档的可编辑文字图层，含隐藏图层。字体可用性以生成报告时这台电脑为准。</p>
<p>可安装原字体后重开工作台，也可在编辑器「文字」菜单中替换缺失字体。替换后复查换行。</p>
</footer>
</main>
</body>
</html>
'''


def main():
    parser = argparse.ArgumentParser(description='检查 PSD、PSB 或 .pcraft 主文档的缺失字体。')
    parser.add_argument('source', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, default=state_path() / 'Reports', help='保存报告的目录。')
    parser.add_argument('--cli', type=Path, default=cli_path())
    args = parser.parse_args()
    try:
        sources = list(dict.fromkeys(path.expanduser().resolve() for path in args.source))
        for source in sources:
            if source.suffix.lower() not in DOCUMENT_TYPES:
                raise ValueError(f'请选择 PSD、PSB 或 .pcraft 稿件　{source.name}')
        binary = args.cli.expanduser().resolve()
        if not binary.is_file():
            raise ValueError('找不到 PhotoCraft CLI。请先运行 P一下.command 安装工作台。')
        report = render_report(Editor(binary), sources)
        directory = args.output.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        prefix = datetime.now().strftime('字体检查-%Y%m%d-%H%M%S-')
        with tempfile.TemporaryDirectory(prefix='.layerlight-', dir=directory) as temp_dir:
            temp = Path(temp_dir)
            draft = temp / 'report.html'
            draft.write_text(report, encoding='utf-8')
            output = directory / (prefix + temp.name.removeprefix('.layerlight-') + '.html')
            draft.rename(output)
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f'字体检查失败　{error}\n')
    print(output)


if __name__ == '__main__':
    main()
