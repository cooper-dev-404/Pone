#!/usr/bin/env bash
set -euo pipefail

workbench="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; exit(sys.version_info < (3, 9))'; then
    printf '%s\n' '批量套版需要 Python 3.9 或更新版本。' >&2
    exit 1
fi

if [[ "$#" -gt 0 ]]; then
    exec python3 -B "$workbench/template_batch.py" "$@"
fi
if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' '请传入 .pcraft 模板和 CSV 数据表的路径。' >&2
    exit 2
fi
template="$(osascript -e 'POSIX path of (choose file with prompt "选择可编辑的 .pcraft 套版模板")')" || exit 0
data="$(osascript -e 'POSIX path of (choose file with prompt "选择 UTF-8 CSV 数据表")')" || exit 0
destination="$(osascript -e 'POSIX path of (choose folder with prompt "选择套版成品存放的位置")')" || exit 0
result="$(python3 -B "$workbench/template_batch.py" "$template" "$data" --output "$destination")"
printf '套版完成：%s\n' "$result"
open "$result"
