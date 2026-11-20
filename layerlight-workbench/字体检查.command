#!/usr/bin/env bash
set -euo pipefail

workbench="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; exit(sys.version_info < (3, 9))'; then
    printf '%s\n' '字体检查需要 Python 3.9 或更新版本。' >&2
    exit 1
fi

if [[ "$#" -gt 0 ]]; then
    exec python3 -B "$workbench/font_check.py" "$@"
fi
if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' '请传入 PSD、PSB 或 .pcraft 稿件的路径。' >&2
    exit 2
fi
source="$(osascript -e 'POSIX path of (choose file with prompt "选择要检查字体的稿件")')" || exit 0
report="$(python3 -B "$workbench/font_check.py" "$source")"
open "$report"
