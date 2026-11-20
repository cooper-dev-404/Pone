#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' '编辑器界面预览需要 macOS。' >&2
    exit 1
fi

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
state="${LAYERLIGHT_HOME:-"$HOME/Library/Application Support/Layerlight Workbench"}"
version=0.23.1
revision=45066c48292e92229ada3459a83453439514c83d
toolchain=1.95.0
i18n_revision=e02939ef009218e81c44e8ec001fbb7603461de4
fonts_revision=b076417b5880bd4154bd22f00695b1d28c6bea83

if ! command -v cargo >/dev/null || ! cargo +"$toolchain" --version >/dev/null; then
    printf '需要 Rust %s。请运行 rustup toolchain install %s --profile minimal\n' "$toolchain" "$toolchain" >&2
    exit 1
fi
mkdir -p -- "$state"
state="$(cd -- "$state" && pwd -P)"
edition="$state/Editor Preview"

staging=
scratch=
cleanup() {
    if [[ -n "$staging" ]]; then rm -rf -- "$staging"; fi
    if [[ -n "$scratch" ]]; then rm -rf -- "$scratch"; fi
}
trap cleanup EXIT

if [[ -n "${PYIXIA_EDITOR_BUILD_DIR:-}" ]]; then
    mkdir -p -- "$PYIXIA_EDITOR_BUILD_DIR"
    build="$(cd -- "$PYIXIA_EDITOR_BUILD_DIR" && pwd)"
else
    scratch="$(mktemp -d "${TMPDIR:-/tmp}/pyixia-editor-ui.XXXXXX")"
    build="$scratch"
fi

archive() {
    local repo="$1" pin="$2" name="$3" expected="$4"
    local file="$build/$name.tar.gz"
    if [[ ! -f "$file" ]]; then
        curl --fail --location --show-error --retry 2 \
            "https://codeload.github.com/storytold/$repo/tar.gz/$pin" -o "$file.download"
        mv -- "$file.download" "$file"
    fi
    local actual
    actual="$(shasum -a 256 "$file" | awk '{print $1}')"
    if [[ "$actual" != "$expected" ]]; then
        printf '源码归档 SHA-256 校验失败 %s\n' "$file" >&2
        return 1
    fi
    if [[ ! -d "$build/$repo-$pin" ]]; then
        tar -xzf "$file" -C "$build"
    fi
}

archive photocraft "$revision" source 77adae07cb30939347b23a15c64e31a0f336ac065a0b82cade5e16d5ed451938
archive craft-i18n "$i18n_revision" translations 0bd1481c0de61d0e31dd2dd9f955135e573f8ebdbb04a87f4567125674b350bd
archive craft-fonts "$fonts_revision" fonts 35eadfeb7e4217a933f24b73a3d190b90fed81e6c933266f092c161746c0a9eb

source_dir="$build/photocraft-$revision"
patch_file="$here/photocraft-$version.patch"
cd -- "$source_dir"
if ! git apply --reverse --check "$patch_file" 2>/dev/null; then
    git apply "$patch_file"
fi

export CRAFT_I18N_DIR="$build/craft-i18n-$i18n_revision"
export CRAFT_FONTS_DIR="$build/craft-fonts-$fonts_revision"
export CRAFT_FONTS_REQUIRED=1
export MACOSX_DEPLOYMENT_TARGET=11.0
export PHOTOCRAFT_BUILD_SHA="$revision"
export CARGO_TARGET_DIR="$build/target"
export CARGO_PROFILE_RELEASE_LTO=false
export CARGO_PROFILE_RELEASE_OPT_LEVEL=2
export CARGO_PROFILE_RELEASE_CODEGEN_UNITS=8
export CARGO_PROFILE_RELEASE_STRIP=debuginfo
export CARGO_NET_GIT_FETCH_WITH_CLI=true
cargo +"$toolchain" build --locked --release --jobs 4 -p photocraft --features heif

mkdir -p -- "$edition"
staging="$(mktemp -d "$edition/.bundle.XXXXXX")"
bundle="$staging/P一下.app"
mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources/Licenses"
install -m755 "$CARGO_TARGET_DIR/release/photocraft" "$bundle/Contents/MacOS/photocraft"
cp -- "$here/Info.plist" "$bundle/Contents/Info.plist"
plutil -insert LSEnvironment -xml '<dict/>' "$bundle/Contents/Info.plist"
plutil -insert LSEnvironment.PHOTOCRAFT_CONFIG_DIR -string "$state/profiles/$version-ui" "$bundle/Contents/Info.plist"
cp -- "$here/Pyixia.icns" "$bundle/Contents/Resources/Pyixia.icns"
cp -- "$source_dir"/{LICENSE-MIT,LICENSE-APACHE,NOTICE,ATTRIBUTION.md} "$bundle/Contents/Resources/Licenses/"
find "$CRAFT_FONTS_DIR" -name 'OFL*.txt' -exec cp -n {} "$bundle/Contents/Resources/Licenses/" \;
plutil -lint "$bundle/Contents/Info.plist"
codesign --sign - "$bundle"
codesign --verify --deep --strict "$bundle"
"$bundle/Contents/MacOS/photocraft" --version

destination="$edition/P一下.app"
if [[ -e "$destination" ]]; then
    previous="$edition/P一下（上次构建）.app"
    if [[ -e "$previous" ]]; then
        previous="$edition/P一下（$(date +%Y%m%d-%H%M%S)-$$）.app"
    fi
    mv -- "$destination" "$previous"
    if ! mv -- "$bundle" "$destination"; then
        mv -- "$previous" "$destination"
        exit 1
    fi
    printf '上一版预览保留在 %s\n' "$previous"
else
    mv -- "$bundle" "$destination"
fi
LAYERLIGHT_HOME="$state" bash "$here/../P一下.command" --preview-ui --version
printf '编辑器预览已构建 %s\n' "$destination"
