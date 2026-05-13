#!/usr/bin/env bash
# Shared runtime profile loader for tooling scripts.
set -euo pipefail

niblit_profile_root() {
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cd "$here/.." && pwd
}

niblit_apply_profile() {
    local profile="${1:-niblit}"
    local root
    root="$(niblit_profile_root)"
    local profile_file="$root/runtime_profiles/${profile}.env"

    if [ ! -f "$profile_file" ]; then
        echo "[runtime-profile] unknown profile: $profile" >&2
        echo "[runtime-profile] expected file: $profile_file" >&2
        return 1
    fi

    set -a
    # shellcheck disable=SC1090
    source "$profile_file"
    set +a

    export NIBLIT_RUNTIME_PROFILE="$profile"
}
