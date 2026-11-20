#!/usr/bin/env bash
set -euo pipefail
workbench="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$workbench/P一下.command" "$@"
