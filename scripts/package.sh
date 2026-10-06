#!/usr/bin/env bash
# Build the Decky Loader plugin zip: out/wake-dispatch.zip
#
# The zip holds exactly one top-level folder, wake-dispatch/, containing what
# Decky Loader needs at runtime: plugin.json, package.json, main.py,
# py_modules/ (minus caches), dist/ (the bundled frontend, minus source maps),
# LICENSE, README.md.
#
# Usage:
#   scripts/package.sh [--no-build] [--version X.Y.Z]
#
#   --no-build        Skip `pnpm install --frozen-lockfile && pnpm build` and
#                     package the existing dist/.
#   --version X.Y.Z   Stamp this version into the packaged copy of
#                     package.json (the working tree is never modified). Used
#                     by the release workflow so the zip always reports the
#                     version of the git tag it was built from.
#
# Environment:
#   PNPM   pnpm command to use (default: pnpm). May contain arguments, e.g.
#          PNPM="npx -y pnpm@9.15.9" scripts/package.sh
set -euo pipefail

PLUGIN_DIR_NAME="wake-dispatch"
ZIP_NAME="${PLUGIN_DIR_NAME}.zip"
REQUIRED=(plugin.json package.json main.py py_modules dist/index.js LICENSE README.md)

die() {
  echo "package.sh: error: $*" >&2
  exit 1
}

build=1
version=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) build=0 ;;
    --version)
      [ $# -ge 2 ] || die "--version needs a value"
      version="$2"
      shift
      ;;
    --version=*) version="${1#--version=}" ;;
    -h | --help)
      # Print the header comment block (everything after the shebang).
      awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

if [ -n "$version" ] && ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  die "--version must be X.Y.Z (got '$version')"
fi

command -v python3 >/dev/null 2>&1 || die "python3 is required (used to write the zip)"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [ "$build" -eq 1 ]; then
  read -r -a pnpm_cmd <<<"${PNPM:-pnpm}"
  echo "==> ${pnpm_cmd[*]} install --frozen-lockfile"
  "${pnpm_cmd[@]}" install --frozen-lockfile
  echo "==> ${pnpm_cmd[*]} build"
  "${pnpm_cmd[@]}" build
fi

missing=()
for path in "${REQUIRED[@]}"; do
  [ -e "$path" ] || missing+=("$path")
done
if [ "${#missing[@]}" -gt 0 ]; then
  die "missing required file(s): ${missing[*]}"
fi

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
dest="$stage/$PLUGIN_DIR_NAME"
mkdir -p "$dest"

cp plugin.json package.json main.py LICENSE README.md "$dest/"
cp -R dist "$dest/dist"
cp -R py_modules "$dest/py_modules"
find "$dest" \( -name '__pycache__' -o -name '*.pyc' -o -name '*.pyo' -o -name '*.map' \) -prune -exec rm -rf {} +

if [ -n "$version" ]; then
  # Rewrite only the staged copy; the repo's package.json is left untouched.
  VERSION="$version" PKG="$dest/package.json" node -e '
    const fs = require("fs");
    const pkg = JSON.parse(fs.readFileSync(process.env.PKG, "utf8"));
    pkg.version = process.env.VERSION;
    fs.writeFileSync(process.env.PKG, JSON.stringify(pkg, null, 2) + "\n");
  '
  echo "==> stamped version ${version} into ${PLUGIN_DIR_NAME}/package.json"
fi

mkdir -p out
rm -f "out/$ZIP_NAME"
# python3's zipfile is used instead of zip(1) so the only requirement is the
# Python that the backend already needs.
(cd "$stage" && python3 -m zipfile -c "$root/out/$ZIP_NAME" "$PLUGIN_DIR_NAME")

# Self-check the archive layout: one top-level folder, every required file.
python3 - "out/$ZIP_NAME" "$PLUGIN_DIR_NAME" "${REQUIRED[@]}" <<'PY'
import sys
import zipfile

zip_path, top, *required = sys.argv[1:]
names = zipfile.ZipFile(zip_path).namelist()
tops = {n.split("/", 1)[0] for n in names}
if tops != {top}:
    sys.exit(f"package.sh: error: expected one top-level folder {top}/, got {sorted(tops)}")
for req in required:
    prefix = f"{top}/{req}"
    if not any(n == prefix or n.startswith(prefix + "/") for n in names):
        sys.exit(f"package.sh: error: {prefix} missing from {zip_path}")
bad = [n for n in names if "__pycache__" in n or n.endswith((".pyc", ".pyo", ".map"))]
if bad:
    sys.exit(f"package.sh: error: caches or source maps in zip: {bad}")
PY

echo "==> out/$ZIP_NAME"
if command -v unzip >/dev/null 2>&1; then
  unzip -l "out/$ZIP_NAME"
else
  python3 -m zipfile -l "out/$ZIP_NAME"
fi
