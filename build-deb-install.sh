#!/usr/bin/env bash
# Build a Debian package (.deb) of Sonar.
#
# Usage:  ./build-deb-install.sh
# Output: dist/sonarex_<version>_all.deb
# Then:   sudo apt install ./dist/sonarex_<version>_all.deb
#
# Built by hand with dpkg-deb rather than with debhelper: Sonar is pure Python
# with no build step, so all the package has to do is put files in the right
# places and name its dependencies. PyQt6 and PyYAML come from the distribution
# (python3-pyqt6, python3-yaml) rather than being bundled, which keeps the
# package architecture-independent and tiny. windowchrome isn't packaged
# anywhere, so its source is copied in from the sibling checkout.
#
# Installed layout:
#   /usr/bin/sonarex                              launcher
#   /usr/lib/sonarex/sonarex/                     the app
#   /usr/lib/sonarex/windowchrome/                copy of ../windowchrome
#   /usr/lib/sonarex/docs/                        HELP.md, USER_GUIDE.md,     }  found through
#                                                 CONFIG.md and img/          }  help.DOCS_DIR
#   /usr/share/applications/sonarex.desktop       menu entry
#   /usr/share/icons/hicolor/*/apps/sonarex.png   themed icon, every size
#
# Note that the program is called "Sonar" while everything installed is named
# "sonarex" — the desktop entry, the config directory and the window class all
# use that name, and __main__ calls setDesktopFileName("sonarex") to tie the
# window to it. Renaming any one of them breaks the icon in the dock.
set -euo pipefail

# Every directory the package creates must be 755 and every file 644 or 755,
# whatever the builder's own umask is (Ubuntu's default 002 would otherwise
# leave /usr, /usr/lib and friends group-writable in the package).
umask 022

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WINDOWCHROME="$HERE/../windowchrome/windowchrome"
DIST="$HERE/dist"
PACKAGE=sonarex
ARCH=all

die() {
  echo "Error: $*" >&2
  exit 1
}

command -v dpkg-deb >/dev/null 2>&1 || die "dpkg-deb not found (it is part of dpkg, on every Debian-based system)."

VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$HERE/pyproject.toml" | head -n 1)"
[ -n "$VERSION" ] || die "could not read the version from pyproject.toml."

[ -f "$WINDOWCHROME/__init__.py" ] || die "windowchrome not found at $WINDOWCHROME.
Clone it beside this folder:  git clone https://github.com/Clay-Ferguson/windowchrome.git ../windowchrome"

# The Maintainer field is whoever builds the package, taken from git unless
# SONAREX_MAINTAINER="Name <email>" says otherwise.
if [ -z "${SONAREX_MAINTAINER:-}" ]; then
  name="$(git -C "$HERE" config user.name || true)"
  email="$(git -C "$HERE" config user.email || true)"
  [ -n "$name" ] && [ -n "$email" ] || die "set git user.name and user.email, or SONAREX_MAINTAINER=\"Name <email>\"."
  SONAREX_MAINTAINER="$name <$email>"
fi

STAGE="$DIST/${PACKAGE}_${VERSION}_${ARCH}"
DEB="$DIST/${PACKAGE}_${VERSION}_${ARCH}.deb"
LIB="$STAGE/usr/lib/$PACKAGE"
rm -rf "$STAGE" "$DEB"

# -- files -------------------------------------------------------------------

install -d -m 755 \
  "$LIB/sonarex" "$LIB/windowchrome" "$LIB/docs" "$LIB/docs/img" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/doc/$PACKAGE" \
  "$STAGE/DEBIAN"

# Both packages are flat directories of modules; __pycache__ is left behind on
# purpose and compiled fresh by postinst.
install -m 644 "$HERE"/sonarex/*.py "$LIB/sonarex/"
install -m 644 "$WINDOWCHROME"/*.py "$LIB/windowchrome/"

# docs/ ships because it is *runtime* content, not just repository
# documentation: Options > Help renders HELP.md and USER_GUIDE.md straight from
# here (help.DOCS_DIR resolves docs/ beside the package). CONFIG.md comes along
# because the User Guide links to it and those links work in the dialog, and
# img/ because the guide embeds a screenshot by relative path — without either,
# help opens on a broken link or a missing image.
install -m 644 "$HERE"/docs/*.md "$LIB/docs/"
install -m 644 "$HERE"/docs/img/*.png "$LIB/docs/img/"

install -m 644 "$HERE/LICENSE.md" "$STAGE/usr/share/doc/$PACKAGE/copyright"

# Icon=sonarex in the desktop entry is a *theme* name, not a path, so the PNGs
# have to land in the hicolor theme for it to resolve. They are checked in at
# every size rather than converted here, which keeps this script free of Pillow
# and ImageMagick; regenerate them with icons/make-icons.py if the artwork
# changes. (sonar-icon.jpeg is that artwork's source and is not installed.)
for icon in "$HERE"/icons/hicolor/*/apps/sonarex.png; do
  size_dir="$(basename "$(dirname "$(dirname "$icon")")")"
  install -d -m 755 "$STAGE/usr/share/icons/hicolor/$size_dir/apps"
  install -m 644 "$icon" "$STAGE/usr/share/icons/hicolor/$size_dir/apps/sonarex.png"
done

# -I (isolated mode) keeps PYTHONPATH and ~/.local site-packages out, so the app
# always runs against the distribution's python3-pyqt6 and python3-yaml rather
# than a pip-installed copy that happens to be lying around.
cat > "$STAGE/usr/bin/$PACKAGE" <<'EOF'
#!/bin/sh
# Sonar launcher, installed by the sonarex package.
exec /usr/bin/python3 -I -c 'import sys; sys.path.insert(0, "/usr/lib/sonarex"); from sonarex.__main__ import main; sys.exit(main())' "$@"
EOF
chmod 755 "$STAGE/usr/bin/$PACKAGE"

# The desktop entry, pointed at the installed launcher. No folder argument on
# the Exec= line: launched from the application grid Sonar opens on the current
# working directory and the folder row is editable anyway. Icon= is already the
# theme name and is rewritten only to keep it pinned to $PACKAGE. The template's
# comment lines are dropped, since they only describe the template.
sed \
  -e '/^#/d' \
  -e "s|^Exec=.*|Exec=$PACKAGE|" \
  -e "s|^Icon=.*|Icon=$PACKAGE|" \
  "$HERE/sonarex.desktop" > "$STAGE/usr/share/applications/sonarex.desktop"
chmod 644 "$STAGE/usr/share/applications/sonarex.desktop"

# -- package metadata --------------------------------------------------------

# Compiled as root at install time, since a user running Sonar can't write
# __pycache__ under /usr/lib; without it every launch compiles in memory.
# The two cache refreshes are what make the icon and the menu entry appear
# without a logout; both are absent on a bare system and harmless when they are.
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  python3 -m compileall -q /usr/lib/sonarex >/dev/null 2>&1 || true
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
EOF

# Removes what postinst compiled, so dpkg can remove the directories it
# installed (it only deletes files it knows about). Runs before upgrades too;
# the new version's postinst compiles again.
cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
find /usr/lib/sonarex -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
EOF

# The icon is gone by now, so the cache has to be rebuilt again or the desktop
# keeps showing it in menus until something else refreshes it.
cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
  update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
EOF
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm" "$STAGE/DEBIAN/postrm"

INSTALLED_SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"

# ugrep is a hard dependency, not a recommendation: Sonar shows a dialog and
# exits without it, so a package that installed without it would be inert.
# poppler-utils (pdftotext) only adds searching *inside* PDFs and xdg-utils only
# backs the default Open command, so both are recommendations.
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.11), python3-pyqt6, python3-yaml, ugrep
Recommends: poppler-utils, xdg-utils, qt6-wayland
Maintainer: $SONAREX_MAINTAINER
Installed-Size: $INSTALLED_SIZE
Homepage: https://github.com/Clay-Ferguson/sonar
Description: recursive file-content search with a two-pane results browser
 Sonar searches the contents of every file under a folder and shows the
 matches in a two-pane window: matching paths on the left, the file itself
 on the right with every match highlighted. ugrep does the searching, so
 queries are Boolean expressions and results stream in as they are found.
 PDFs are rendered in the window, archives can be searched in place, and
 the Open button hands the file to your editor.
EOF

# -- build -------------------------------------------------------------------

# --root-owner-group: files owned by root without needing fakeroot.
# -Zxz: every dpkg can read xz; Ubuntu's default zstd is not readable by
# older Debian dpkg releases.
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$DEB" >/dev/null
rm -rf "$STAGE"

echo "Built $DEB"
echo ""
echo "Install:  sudo apt install $DEB"
echo "Remove:   sudo apt remove $PACKAGE"
# A leftover from the old install.sh, which this package replaced. Its entry in
# ~/.local/share/applications takes precedence over the package's, so it would
# keep launching the checkout after the package is installed.
if [ -f "$HOME/.local/share/applications/sonarex.desktop" ]; then
  echo ""
  echo "Note: a per-user launcher in ~/.local/share/applications hides the"
  echo "package's. Remove it, and the icons install.sh copied, with:"
  echo "  rm ~/.local/share/applications/sonarex.desktop"
  echo "  rm ~/.local/share/icons/hicolor/*/apps/sonarex.png"
fi
