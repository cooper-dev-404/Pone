#!/usr/bin/env bash
set -euo pipefail

workbench="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; exit(sys.version_info < (3, 9))'; then
    printf '%s\n' '链接素材工具需要 Python 3.9 或更新版本。' >&2
    exit 1
fi

if [[ "$#" -gt 0 ]]; then
    exec python3 -B "$workbench/link_handoff.py" "$@"
fi
if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' '请指定 check 或 package，以及 PSD、PSB 或 .pcraft 稿件的路径。' >&2
    exit 2
fi
choice="$(osascript -e 'set picked to choose from list {"检查链接", "打包交接"} with prompt "选择链接素材操作" default items {"检查链接"}' -e 'if picked is false then return ""' -e 'return item 1 of picked')" || exit 0
case "$choice" in
    '检查链接') options=(check) ;;
    '打包交接') options=(package) ;;
    *) exit 0 ;;
esac
source="$(osascript -e 'POSIX path of (choose file with prompt "选择含链接素材的设计稿")')" || exit 0
if [[ "$choice" == '打包交接' ]]; then
    destination="$(osascript -e 'POSIX path of (choose folder with prompt "选择交接包存放的位置")')" || exit 0
    options+=(--output "$destination")
fi
result="$(python3 -B "$workbench/link_handoff.py" "${options[@]}" "$source")"
open "$result"
