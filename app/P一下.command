#!/usr/bin/env bash
set -euo pipefail
umask 077

workbench="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
version=0.23.1
platform="$(uname -s)"
if [[ "$platform" == Darwin ]]; then
    state="${LAYERLIGHT_HOME:-"$HOME/Library/Application Support/Layerlight Workbench"}"
else
    state="${LAYERLIGHT_HOME:-"$HOME/.local/share/layerlight-workbench"}"
fi

profile="$state/profiles/$version"
examples="$state/Examples"
mkdir -p "$profile/Presets" "$examples"

seed() (
    source_file="$1"
    destination="$2"
    [[ -e "$destination" ]] && exit 0
    temporary="$(mktemp "${destination}.XXXXXX")"
    trap 'rm -f -- "$temporary"' EXIT
    cp -- "$source_file" "$temporary"
    # An existing profile or edited example always wins, including on a simultaneous first launch.
    if ! ln -- "$temporary" "$destination" 2>/dev/null; then
        [[ -f "$destination" ]] || exit 1
    fi
)

if [[ "$platform" == Darwin ]]; then
    runtime="$state/runtimes/$version/PhotoCraft.app"
    executable="$runtime/Contents/MacOS/photocraft"
    if [[ ! -x "$executable" ]]; then
        bash "$workbench/install-macos.sh" "${LAYERLIGHT_PHOTOCRAFT_DMG:-}"
    fi
elif [[ "$platform" == Linux && -n "${LAYERLIGHT_EDITOR_BIN:-}" ]]; then
    executable="$LAYERLIGHT_EDITOR_BIN"
else
    printf '%s\n' '请在 macOS 打开 P一下.command。Linux 开发验证可指定 LAYERLIGHT_EDITOR_BIN。' >&2
    exit 1
fi

if [[ ! -x "$executable" ]]; then
    printf '%s\n' '找不到可执行的 PhotoCraft 桌面程序。' >&2
    exit 1
fi

base_version="$("$executable" --version)"
case "$base_version" in
    *" $version "*) ;;
    *) printf '工作台需要 PhotoCraft %s。当前为 %s\n' "$version" "$base_version" >&2; exit 1 ;;
esac

for sample in "$workbench"/../examples/practice/*; do
    seed "$sample" "$examples/$(basename -- "$sample")"
done
seed "$workbench/profile/actions.json" "$profile/Presets/actions.json"

first_launch=false
if [[ ! -f "$profile/preferences.json" ]]; then
    seed "$workbench/profile/preferences.json" "$profile/preferences.json"
    first_launch=true
fi

if [[ "${1:-}" == --remove ]]; then
    shift
    if [[ "$#" -ne 0 ]]; then
        printf '%s\n' '--remove 单独使用可打开移除工具练习稿。' >&2
        exit 2
    fi
    set -- "$examples/移除工具练习.pcraft"
elif [[ "${1:-}" == --fill ]]; then
    shift
    if [[ "$#" -ne 0 ]]; then
        printf '%s\n' '--fill 单独使用可打开内容识别填充练习稿。' >&2
        exit 2
    fi
    set -- "$examples/内容识别填充练习.pcraft"
elif [[ "${1:-}" == --retouch ]]; then
    shift
    if [[ "$#" -ne 0 ]]; then
        printf '%s\n' '--retouch 单独使用可打开复杂边缘练习稿。' >&2
        exit 2
    fi
    set -- "$examples/半透明边缘练习.pcraft"
elif [[ "${1:-}" == --examples ]]; then
    shift
    if [[ "$#" -ne 0 ]]; then
        printf '%s\n' '--examples 单独使用可打开两份示例项目。' >&2
        exit 2
    fi
    set -- "$examples/产品合成.psd" "$examples/横竖版交付.pcraft"
elif [[ "$first_launch" == true && "$#" -eq 0 ]]; then
    set -- "$examples/产品合成.psd" "$examples/横竖版交付.pcraft"
fi

export PHOTOCRAFT_CONFIG_DIR="$profile"
exec "$executable" "$@"
