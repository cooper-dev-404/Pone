#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' '此安装脚本需要 macOS。' >&2
    exit 1
fi

version=0.23.1
sha=606a52917188c65dc71709781180a0e3244e0f3b7f40b2f5b80170e87364420d
state="${LAYERLIGHT_HOME:-"$HOME/Library/Application Support/Layerlight Workbench"}"
runtime="$state/runtimes/$version"
if [[ -x "$runtime/PhotoCraft.app/Contents/MacOS/photocraft" ]]; then exit 0; fi
mkdir -p "$runtime"
staging="$(mktemp -d "$runtime/.install.XXXXXX")"
mount="$staging/volume"
mounted=
cleanup() {
    if [[ "$mounted" == true ]]; then
        hdiutil detach -quiet "$mount" || return
    fi
    rm -rf -- "$staging"
}
trap cleanup EXIT

disk="${1:-}"
if [[ -z "$disk" ]]; then
    printf '%s\n' '下载 PhotoCraft 0.23.1 官方 Mac 安装包，约 274 MB。'
    disk="$staging/photocraft.dmg"
    curl --fail --location --show-error --retry 2 --output "$disk" \
        "https://github.com/storytold/photocraft/releases/download/v$version/photocraft-$version-macos-universal.dmg"
fi

actual="$(shasum -a 256 "$disk" | awk '{print $1}')"
if [[ "$actual" != "$sha" ]]; then
    printf '%s\n' '安装包的 SHA-256 与上游发布值不同。' >&2
    exit 1
fi

mkdir "$mount"
hdiutil attach -readonly -nobrowse -mountpoint "$mount" "$disk" >/dev/null
mounted=true
upstream="$mount/PhotoCraft.app"
if [[ ! -x "$upstream/Contents/MacOS/photocraft" ]]; then
    printf '%s\n' '官方镜像中缺少 PhotoCraft.app。' >&2
    exit 1
fi
ditto "$upstream" "$staging/PhotoCraft.app"
# Disk-image Finder metadata can fail strict validation on macOS.
xattr -rd com.apple.FinderInfo "$staging/PhotoCraft.app"
codesign --verify --deep --strict "$staging/PhotoCraft.app"
mv -n -- "$staging/PhotoCraft.app" "$runtime/"
test -x "$runtime/PhotoCraft.app/Contents/MacOS/photocraft"
printf '已安装 PhotoCraft 编辑器到 %s\n' "$runtime"
