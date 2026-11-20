#!/usr/bin/env bash
# Publish one engine artifact as a GitHub pre-release (release-1.yml, job publish-engine), or check it as that job
# would without publishing (--dry-run, run on every pull request).
#
#   release/engine/publish.sh [--dry-run] DIR        DIR holds fenvix-engine-*.tar.gz and its .sha256
#
# Both modes: exactly one tarball, its .sha256 matches, the tag is engine-<version>-<build>, the pinned URL and
# sha256 the runner image uses are printed, and release/engine/fetch.sh installs the tarball from a file:// URL with
# that sha256 and refuses it with any other (fail closed). Only without --dry-run is the release created.
set -euo pipefail
dry=0; [ "${1:-}" = --dry-run ] && { dry=1; shift; }
dir="$(cd "$1" && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
die() { echo "publish: $*" >&2; exit 1; }
n="$(ls "$dir"/fenvix-engine-*-linux-x86_64.tar.gz | wc -l)"; [ "$n" -eq 1 ] || die "expected one tarball in $dir, found $n"
f="$(cd "$dir" && ls fenvix-engine-*-linux-x86_64.tar.gz)"
(cd "$dir" && sha256sum -c "$f.sha256" >/dev/null) || die "$f does not match $f.sha256"
sha="$(cut -d' ' -f1 "$dir/$f.sha256")"
tag="engine-${f#fenvix-engine-}"; tag="${tag%-linux-x86_64.tar.gz}"
[[ "$tag" =~ ^engine-[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?-r[0-9]+\.[0-9a-f]{7}$ ]] || [ -z "${GITHUB_ACTIONS:-}" ] || die "bad tag $tag (expected engine-<version>-r<run>.<sha7>)"
repo="${GITHUB_REPOSITORY:-Mircoguidetti/fenvix-engine-cli}"
url="https://github.com/$repo/releases/download/$tag/$f"
# the runner image's fetch, against this very file: accepted with the pinned sha256, refused with any other
t="$(mktemp -d)"; trap 'rm -rf "$t"' EXIT
"$here/fetch.sh" "file://$dir/$f" "$sha" "$t/ok" > /dev/null || die "fetch.sh refused the artifact with its own checksum"
if "$here/fetch.sh" "file://$dir/$f" "$(printf '0%.0s' {1..64})" "$t/bad" 2>/dev/null; then die "fetch.sh accepted a wrong checksum"; fi
[ ! -e "$t/bad" ] || die "fetch.sh unpacked an artifact whose checksum differs"
cat > "$t/notes.md" <<NOTES
Engine artifact of claude/release-1 at ${GITHUB_SHA:-$(git rev-parse HEAD)}: Linux x86_64, glibc 2.28+, CPython 3.12-3.14,
Node 22/24/26.

Pin in the runner image: URL \`$url\`, sha256 \`$sha\`.
Fetch and install (fail closed on any other checksum): \`release/engine/fetch.sh <URL> <sha256> /opt/fenvix-dist\`, then
\`PYTHON=python3 <unpacked dir>/install.sh /opt/fenvix\`.
NOTES
echo "tag:    $tag"
echo "url:    $url"
echo "sha256: $sha"
if [ "$dry" -eq 1 ]; then
  echo "dry run: would run: gh release create $tag $f $f.sha256 --repo $repo --target ${GITHUB_SHA:-HEAD} --prerelease"
  cat "$t/notes.md"
  exit 0
fi
gh release create "$tag" "$dir/$f" "$dir/$f.sha256" --repo "$repo" --target "${GITHUB_SHA:?}" --prerelease \
  --title "fenvix engine $tag" --notes-file "$t/notes.md"
