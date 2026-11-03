#!/usr/bin/env bash
# Resolve the PM target before the pinned uv bootstrap.
# Termux is Android/Bionic even though uname reports Linux/aarch64.
noryka_target_for() {
    local os="${1:?OS is required}"
    local arch="${2:?architecture is required}"
    local termux_version="${3:-}"
    local prefix="${4:-}"
    local termux_root="${5:-/data/data/com.termux/files/usr}"

    if [[ "$os" == "linux" ]] && {
        [[ -n "$termux_version" ]] ||
        [[ "$prefix" == *"/com.termux/"* ]] ||
        [[ "$prefix" == *"/com.termux" ]] ||
        [[ -d "$termux_root" ]]
    }; then
        printf 'linux-%s-bionic\n' "$arch"
    else
        printf '%s-%s\n' "$os" "$arch"
    fi
}
