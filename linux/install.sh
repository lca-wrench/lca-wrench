#!/bin/bash
# Installs LCA Wrench into this folder: its own Python 3.12, Brightway and the app.
# Needs internet once, no root password. Nothing outside this folder is changed except the menu entry "LCA Wrench"
# (~/.local/share/applications), which starts it (no PATH, no shell profile, no conda, no Brightway projects).
set -euo pipefail
cd "$(dirname "$0")"
DIR="$PWD"
# edition.env (only in other editions, e.g. LCA Wrench Extended): own name and port, so it runs next to LCA Wrench
NAME="LCA Wrench"; ID=""; DEFAULT_PORT=8787
if [ -f edition.env ]; then
  while IFS='=' read -r k v || [ -n "$k" ]; do
    v="${v%$'\r'}"
    case "$k" in NAME) NAME="$v" ;; ID) ID="$v" ;; PORT) DEFAULT_PORT="$v" ;; esac
  done < edition.env
fi
UV_VERSION="0.9.5"
export UV_PYTHON_INSTALL_DIR="$DIR/.tools/python"   # Python stays inside this folder
export UV_CACHE_DIR="$DIR/.tools/cache"
export UV_PYTHON_PREFERENCE=only-managed           # never use another Python of this computer (system, conda)

pause() { if [ -t 0 ]; then echo; read -n 1 -s -r -p "Press any key to close"; echo; fi; }
fail() { echo; echo "ERROR: $1"; echo "Log: $DIR/installation-log.txt"; pause; exit 1; }
trap 'fail "Installation stopped (line $LINENO). Check the internet connection and run it again."' ERR

# Runs only from the release package (pack_linux.sh puts this script next to lca_wrench and the requirements).
# Started from a clone or from "Source code (zip)", nothing fits: stop before anything is written here.
if [ ! -f requirements-lock.txt ]; then
  echo "ERROR: this folder is not the LCA Wrench installation package (it looks like the source code)."
  echo "Download LCA-Wrench-Linux.tar.gz from the release page and run install.sh there:"
  echo "  https://github.com/lca-wrench/lca-wrench/releases/latest"
  echo "\"Source code (zip)\" on that page is not the installer. To run from source, see \"From source\" in README.md."
  pause; exit 1
fi

mkdir -p "$DIR/.tools" 2>/dev/null && touch "$DIR/.tools/.write-test" 2>/dev/null && rm -f "$DIR/.tools/.write-test" \
  || { echo "ERROR: no write access to $DIR"
       echo "Unpack the package into a folder of your own, e.g. in your home folder."
       pause; exit 1; }
exec > >(tee "$DIR/installation-log.txt") 2>&1

echo "$NAME: installation"
echo "Folder: $DIR"
echo "$( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || uname -s), $(uname -m)"
echo

# every file of the package must be here (FILES.txt, written when packing): a partial copy, e.g. over an older
# folder, otherwise fails only later, when LCA Wrench runs
if [ -f FILES.txt ]; then
  MISSING=()
  while IFS= read -r f || [ -n "$f" ]; do
    f="${f%$'\r'}"
    if [ -n "$f" ] && [ ! -e "$f" ]; then MISSING+=("$f"); fi   # if, not &&: set -e and the ERR trap
  done < FILES.txt
  if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Missing in this folder (${#MISSING[@]} files), e.g.:"
    printf '  %s\n' "${MISSING[@]:0:5}"
    fail "This folder is incomplete. Delete its folder lca_wrench, unpack the archive over it again and run ./install.sh again (README.txt, \"Updating\"). Or install into a new, empty folder."
  fi
fi

UV="$DIR/.tools/uv"
if [ ! -x "$UV" ]; then
  echo "1/3  Loading the installer tool uv $UV_VERSION …"
  # The release archive straight from GitHub, checked against a pinned checksum. No install script:
  # astral's install.sh also writes ~/.config/uv and aborts if that folder is not writable.
  # Python and the packages need glibc (most distributions); musl (Alpine) is not supported.
  if ldd --version 2>&1 | grep -qi musl; then fail "This Linux uses musl (e.g. Alpine). LCA Wrench needs a glibc-based distribution."; fi
  case "$(uname -m)" in
    x86_64|amd64)  UV_ARCH=x86_64-unknown-linux-gnu;  UV_SHA=2cf10babba653310606f8b49876cfb679928669e7ddaa1fb41fb00ce73e64f66 ;;
    aarch64|arm64) UV_ARCH=aarch64-unknown-linux-gnu; UV_SHA=9db0c2f6683099f86bfeea47f4134e915f382512278de95b2a0e625957594ff3 ;;
    *) fail "Processor $(uname -m) is not supported (x86_64 or aarch64 needed)." ;;
  esac
  TGZ="$DIR/.tools/uv.tar.gz"
  URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_ARCH.tar.gz"
  if command -v curl >/dev/null; then
    curl -LfsS --retry 3 --connect-timeout 20 -o "$TGZ" "$URL" \
      || fail "Download of uv failed (github.com). Check the internet connection and run it again."
  elif command -v wget >/dev/null; then
    wget -q --tries=3 --timeout=20 -O "$TGZ" "$URL" \
      || fail "Download of uv failed (github.com). Check the internet connection and run it again."
  else
    fail "Neither curl nor wget is installed. Install one of them (e.g. sudo apt install curl) and run it again."
  fi
  [ "$(sha256sum "$TGZ" | cut -d' ' -f1)" = "$UV_SHA" ] || fail "uv download corrupted, run it again."
  tar -xzf "$TGZ" -C "$DIR/.tools" --strip-components 1
  rm -f "$TGZ"
  [ -x "$UV" ] || fail "uv not found."
fi

echo "2/3  Loading Python 3.12 …"
"$UV" venv --quiet --allow-existing --python 3.12 "$DIR/.venv"

echo "3/3  Loading Brightway and the app, this takes a few minutes …"
# requirements-lock.txt holds the SHA-256 checksum of every package file: uv installs a file only when it matches.
# A mismatch stops the installation; only versions that do not fit this computer fall back to the newest matching
# ones (requirements-app.txt, without checksums).
ERRS="$DIR/.tools/lock-errors.txt"
if ! "$UV" pip install --quiet --require-hashes --python "$DIR/.venv/bin/python" -r requirements-lock.txt 2> "$ERRS"; then
  cat "$ERRS"
  if grep -qi "hash mismatch" "$ERRS"; then
    fail "A downloaded package does not match its checksum, so it was not installed. Run the installation again later; if it happens again, send installation-log.txt."
  fi
  echo "     The tested versions do not fit this computer, using the newest matching ones (without checksums) …"
  "$UV" pip install --quiet --python "$DIR/.venv/bin/python" -r requirements-app.txt
fi
rm -f "$ERRS"
"$DIR/.venv/bin/python" -c "import bw2data, bw2calc, bw2io, fastapi, uvicorn, sentier_brightway, ecoinvent_interface" >/dev/null 2>&1 || fail "Installation check failed."
rm -rf "$DIR/.tools/cache"  # downloads only, about 300 MB

trap - ERR

# menu entry "LCA Wrench" with the logo (freedesktop.org desktop entry, read by GNOME, KDE, Xfce ...): it runs
# start.sh of this folder in a terminal window
chmod +x "$DIR/start.sh"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/lca-wrench${ID:+-$ID}.desktop"
if [[ "$DIR" == *[\"\`\$\\]* ]]; then
  echo "No menu entry: the folder path contains one of the characters \" \` \$ \\. Start with ./start.sh in this folder."
elif mkdir -p "$APPS" 2>/dev/null && cat > "$ENTRY" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$NAME
Comment=Local web interface for Brightway (life cycle assessment)
Exec="$DIR/start.sh"
Path=$DIR
Icon=$DIR/lca_wrench/static/logo.svg
Terminal=true
Categories=Science;Education;
DESKTOP
then
  echo "The menu entry \"$NAME\" is in the applications menu: start it from there."
else
  echo "No menu entry (no access to $APPS)."
fi

echo
echo "Done. Start $NAME from the applications menu, or with ./start.sh in this folder."
echo "You can close this window."
