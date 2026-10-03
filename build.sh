#!/usr/bin/env bash
# Build the .deb and, if you say yes, install it.
#
#   ./build.sh
#
# A convenience wrapper: packaging/build-deb.sh does all the building, and this
# only offers to run the `sudo apt install --reinstall` it would otherwise
# print. The prompt defaults to no, and is skipped when stdin isn't a terminal,
# so a scripted run only builds.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

"$HERE/packaging/build-deb.sh"

# The same name build-deb.sh gives the package; recomputed rather than parsed
# out of its output, so a change to that script's messages can't break this.
VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$HERE/pyproject.toml" | head -n 1)"
DEB="$HERE/dist/sonarex_${VERSION}_all.deb"
if [ ! -f "$DEB" ]; then
  echo "Error: expected $DEB after the build, but it isn't there." >&2
  exit 1
fi

[ -t 0 ] || exit 0

echo ""
read -r -p "Install it now with sudo apt install --reinstall? [y/N] " answer
case "$answer" in
  [yY] | [yY][eE][sS])
    # An absolute path, so apt treats it as a file rather than a package name.
    # --reinstall because a rebuild keeps the version from pyproject.toml, and
    # without it apt sees that version already installed and skips the .deb
    # ("sonarex is already the newest version"). Harmless on a first install.
    sudo apt install --reinstall "$DEB"
    ;;
  *)
    echo "Not installed."
    ;;
esac
