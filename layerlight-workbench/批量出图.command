#!/usr/bin/env bash
set -euo pipefail

workbench="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; exit(sys.version_info < (3, 9))'; then
    printf '%s\n' '批量出图需要 Python 3.9 或更新版本。' >&2
    exit 1
fi

platform="$(uname -s)"
if [[ "$#" -gt 0 ]]; then
    exec python3 -B "$workbench/batch_export.py" "$@"
fi
if [[ "$platform" != Darwin ]]; then
    printf '%s\n' '请传入要出图的文件路径。' >&2
    exit 2
fi
choice="$(osascript -e 'set picked to choose from list {"整图与画板", "标记图层", "图像切片", "图层与切片"} with prompt "选择本次出图内容" default items {"整图与画板"}' -e 'if picked is false then return ""' -e 'return item 1 of picked')" || exit 0
case "$choice" in
    '整图与画板') mode=document ;;
    '标记图层') mode=layers ;;
    '图像切片') mode=slices ;;
    '图层与切片') mode=assets ;;
    *) exit 0 ;;
esac
source_file="$(osascript -e 'POSIX path of (choose file with prompt "选择要交付的设计稿")')" || exit 0
options=(--mode "$mode")
if [[ "$mode" != document ]]; then
    scales="$(osascript -e 'text returned of (display dialog "用逗号分隔倍率，例如 1,1.5,2" default answer "1,2" with title "素材出图倍率")')" || exit 0
    options+=(--scales "$scales")
fi
output_folder="$(osascript -e 'POSIX path of (choose folder with prompt "选择交付结果存放的位置")')" || exit 0
result="$(python3 -B "$workbench/batch_export.py" "$source_file" "${options[@]}" --output "$output_folder")"
printf '出图完成：%s\n' "$result"
open "$result"
