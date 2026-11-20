#!/usr/bin/env bash
# Fetch the engine artifact for a runner image: a pinned URL and its pinned sha256, fail closed.
#
#   release/engine/fetch.sh URL SHA256 DEST_DIR
#
# Downloads URL (https://, or file:// for a local copy) to a temporary file, compares its sha256 with SHA256 and only
# then unpacks it into DEST_DIR (prints the unpacked engine directory). A different checksum, a download error, a
# missing argument or an archive with paths outside its one top directory: nothing is unpacked, exit 1.
set -euo pipefail
url="${1:-}"; want="${2:-}"; dest="${3:-}"
die() { echo "fetch: $*" >&2; exit 1; }
[ -n "$url" ] && [ -n "$dest" ] || die "usage: fetch.sh URL SHA256 DEST_DIR"
[[ "$want" =~ ^[0-9a-f]{64}$ ]] || die "a pinned sha256 (64 hex digits) is required, got '${want}'"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
f="$tmp/engine.tar.gz"
curl -fsSL --proto '=https,file' --retry 3 -o "$f" "$url" || die "download failed: $url"
got="$(sha256sum "$f" | cut -d' ' -f1)"
[ "$got" = "$want" ] || die "checksum mismatch for $url: expected $want, got $got (nothing installed)"
top="$(tar -tzf "$f" | cut -d/ -f1 | sort -u)"
[ "$(echo "$top" | wc -l)" -eq 1 ] && [[ "$top" == fenvix-engine-* ]] || die "unexpected archive layout: $top"
if tar -tzf "$f" | grep -qE '(^/|(^|/)\.\.(/|$))'; then die "archive has absolute or parent paths"; fi
mkdir -p "$dest"
tar -xzf "$f" -C "$dest"
echo "$dest/$top"
