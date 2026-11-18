#!/bin/bash
# Installs LCA Wrench into this folder: its own Python 3.12, Brightway and the app.
# Needs internet once, no admin password. Nothing outside this folder is changed except the app "LCA Wrench"
# on the desktop, which starts it (no PATH, no shell profile, no conda, no Activity Browser, no Brightway projects).
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
export UV_PYTHON_PREFERENCE=only-managed           # never use another Python of this Mac (conda, Homebrew)

pause() { if [ -t 0 ]; then echo; read -n 1 -s -r -p "Press any key to close"; echo; fi; }
fail() { echo; echo "ERROR: $1"; echo "Log: $DIR/installation-log.txt"; pause; exit 1; }
trap 'fail "Installation stopped (line $LINENO). Check the internet connection and run it again."' ERR

# Runs only from the release package (pack_mac.sh puts this script next to lca_wrench and the requirements).
# Started from a clone or from "Source code (zip)", nothing fits: stop before anything is written here.
if [ ! -f requirements-lock.txt ]; then
  echo "ERROR: this folder is not the LCA Wrench installation package (it looks like the source code)."
  echo "Download LCA-Wrench-Mac.zip from the release page and open \"Install LCA Wrench\" there:"
  echo "  https://github.com/lca-wrench/lca-wrench/releases/latest"
  echo "\"Source code (zip)\" on that page is not the installer. To run from source, see \"From source\" in README.md."
  pause; exit 1
fi

mkdir -p "$DIR/.tools" 2>/dev/null && touch "$DIR/.tools/.write-test" 2>/dev/null && rm -f "$DIR/.tools/.write-test" \
  || { echo "ERROR: no write access to $DIR"
       echo "Move the folder to Documents, or allow Terminal access (System Settings → Privacy & Security → Files and Folders)."
       pause; exit 1; }
exec > >(tee "$DIR/installation-log.txt") 2>&1

echo "$NAME: installation"
echo "Folder: $DIR"
echo "macOS $(sw_vers -productVersion), $(uname -m)"
echo

# every file of the package must be here (FILES.txt, written when packing): a partial copy, e.g. over an older
# folder or through OneDrive, otherwise fails only later, when LCA Wrench runs
if [ -f FILES.txt ]; then
  MISSING=()
  while IFS= read -r f || [ -n "$f" ]; do
    f="${f%$'\r'}"
    if [ -n "$f" ] && [ ! -e "$f" ]; then MISSING+=("$f"); fi   # if, not &&: set -e and the ERR trap
  done < FILES.txt
  if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Missing in this folder (${#MISSING[@]} files), e.g.:"
    printf '  %s\n' "${MISSING[@]:0:5}"
    fail "This folder is incomplete. Unpack the zip again into a new, empty folder (not over an older one) and run the installation there."
  fi
fi

UV="$DIR/.tools/uv"
if [ ! -x "$UV" ]; then
  echo "1/3  Loading the installer tool uv $UV_VERSION …"
  # The release archive straight from GitHub, checked against a pinned checksum. No install script:
  # astral's install.sh also writes ~/.config/uv and aborts if that folder is not writable.
  case "$(uname -m)" in
    arm64) UV_ARCH=aarch64-apple-darwin; UV_SHA=dc098ff224d78ed418e121fd374f655949d2c7031a70f6f6604eaf016a130433 ;;
    *)     UV_ARCH=x86_64-apple-darwin;  UV_SHA=58b1d4a25aa8ff99147c2550b33dcf730207fe7e0f9a0d5d36a1bbf36b845aca ;;
  esac
  TGZ="$DIR/.tools/uv.tar.gz"
  curl -LfsS --retry 3 --connect-timeout 20 -o "$TGZ" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_ARCH.tar.gz" \
    || fail "Download of uv failed (github.com). Check the internet connection and run it again."
  [ "$(shasum -a 256 "$TGZ" | cut -d' ' -f1)" = "$UV_SHA" ] || fail "uv download corrupted, run it again."
  tar -xzf "$TGZ" -C "$DIR/.tools" --strip-components 1
  rm -f "$TGZ"
  [ -x "$UV" ] || fail "uv not found."
fi

echo "2/3  Loading Python 3.12 …"
"$UV" venv --quiet --allow-existing --python 3.12 "$DIR/.venv"

echo "3/3  Loading Brightway and the app, this takes a few minutes …"
# requirements-lock.txt holds the SHA-256 checksum of every package file: uv installs a file only when it matches.
# A mismatch stops the installation; only versions that do not fit this Mac fall back to the newest matching ones
# (requirements-app.txt, without checksums).
ERRS="$DIR/.tools/lock-errors.txt"
if ! "$UV" pip install --quiet --require-hashes --python "$DIR/.venv/bin/python" -r requirements-lock.txt 2> "$ERRS"; then
  cat "$ERRS"
  if grep -qi "hash mismatch" "$ERRS"; then
    fail "A downloaded package does not match its checksum, so it was not installed. Run the installation again later; if it happens again, send installation-log.txt."
  fi
  echo "     The tested versions do not fit this Mac, using the newest matching ones (without checksums) …"
  "$UV" pip install --quiet --python "$DIR/.venv/bin/python" -r requirements-app.txt
fi
rm -f "$ERRS"
"$DIR/.venv/bin/python" -c "import bw2data, bw2calc, bw2io, fastapi, uvicorn, sentier_brightway, ecoinvent_interface" >/dev/null 2>&1 || fail "Installation check failed."
rm -rf "$DIR/.tools/cache"  # downloads only, about 300 MB

trap - ERR

# "LCA Wrench.app" with the logo, here and on the desktop: it opens "Start LCA Wrench" of this folder
make_app() {
  local APP="$1/$NAME.app"
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" || return 1
  cp "$DIR/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>ch.lca-wrench.launcher${ID:+.$ID}</string>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
  cat > "$APP/Contents/MacOS/$NAME" <<LAUNCH
#!/bin/bash
# Starts $NAME from its folder (written by the installer).
START="$DIR/Start LCA Wrench.command"
if [ ! -f "\$START" ]; then
  osascript -e 'display alert "$NAME" message "The $NAME folder has moved. Run \"Install LCA Wrench\" in its new place again."'
  exit 1
fi
open "\$START"
LAUNCH
  chmod +x "$APP/Contents/MacOS/$NAME"
  touch "$APP"
}
make_app "$DIR" || true
# also in the user's own Applications folder (~/Applications, no administrator rights), so Spotlight and Launchpad
# find it like any other app
mkdir -p "$HOME/Applications" 2>/dev/null && make_app "$HOME/Applications" 2>/dev/null || true
if make_app "$HOME/Desktop" 2>/dev/null; then
  echo "The app \"$NAME\" is on the desktop (and in this folder): double-click it to start."
else
  echo "Start $NAME with \"$NAME\" in this folder (no access to the desktop)."
fi

echo
echo "Done. Start $NAME with the app \"$NAME\" on the desktop, or \"Start LCA Wrench\" in this folder."
echo "You can close this window."
