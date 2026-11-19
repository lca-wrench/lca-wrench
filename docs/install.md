# Installation

Two routes: the release packages (no terminal needed) and installation from source. For the short version see the
[README](../README.md#install).

## Release packages

`LCA-Wrench-Mac.zip`, `LCA-Wrench-Windows.zip` and `LCA-Wrench-Linux.tar.gz` are attached to the
[GitHub release](https://github.com/lca-wrench/lca-wrench/releases). Each contains the app, `requirements-lock.txt`
(the tested package versions), a `README.txt` (English first, German below) and two scripts: install and start. On
macOS these are packed inside an installer app (below).

The Windows and Linux packages have been tested less than the macOS one.

### macOS

- `LCA-Wrench-Mac.zip` holds **Install LCA Wrench.app**, signed with a Developer ID and notarized by Apple, so macOS
  only asks once whether to open an app downloaded from the internet. The app contains the folder `LCA-Wrench` (the
  app code, the two double-click scripts, `README.txt`, the lock files, the licence). It asks where to install
  (default `~/LCA-Wrench`, or "Other folder…": a folder `LCA-Wrench` inside the chosen one), copies the folder there
  without the "downloaded from the internet" mark, and opens "Install LCA Wrench" in that folder. An existing folder is
  only used if it is an LCA Wrench folder: then this is an update, the app code is replaced and the Python, the
  packages and the log stay. Sources: `mac/installer/` (`bootstrap.sh`, and `launcher.c`, the small main executable
  that runs it). The app is self-contained because macOS runs downloaded apps from a temporary read-only location.
- **Install LCA Wrench** (the script in the installed folder) downloads the tool `uv` and, with it, its own Python 3.12 and the packages. Everything goes
  into the unpacked folder: no administrator password, no change to PATH, no conda. An internet connection and a few
  minutes are needed. If the tested versions do not fit the computer (for example an older Intel Mac), the installer takes the
  same Brightway versions from `requirements-app.txt` and the newest matching versions of the other packages.
- **Start LCA Wrench** starts the app on port 8787 and opens the browser. Closing the terminal window stops it.
- At the end the installer puts an app **LCA Wrench** with the logo on the desktop, into `~/Applications` (so
  Spotlight and Launchpad find it) and into the folder. It is a small
  launcher (`LCA Wrench.app`, icon `mac/AppIcon.icns`) that opens "Start LCA Wrench" of this folder. It is created on the
  computer itself, so macOS does not block it. If the folder is moved, the launcher says so and the installer creates it
  again.
- If the folder is in Documents, Desktop or Downloads, macOS asks for Terminal access to it; the home folder avoids
  that.
- A package built without a signature (see below) is the plain folder with the double-click scripts. macOS blocks
  them the first time: right-click, "Open"; on newer versions System Settings, Privacy & Security, "Open Anyway".
  Transferring the folder by USB stick does not set this block.

### Windows

Files are in `windows/`.

- **Install LCA Wrench.cmd** runs `install.ps1` (Windows PowerShell 5.1, present on Windows 10 and 11). It downloads
  `uv` 0.9.5 from GitHub (fixed checksum) and, with it, its own Python 3.12 and the packages of
  `requirements-lock.txt`, all only into the unpacked folder (no administrator rights, no PATH, no registry). The
  fallback to `requirements-app.txt` works as on macOS.
- **Start LCA Wrench.cmd** starts the app on port 8787 and opens the browser. Closing the window stops it. The
  installer also creates a desktop shortcut **LCA Wrench** with the logo (`windows/lca-wrench.ico`).
- `uvloop` does not exist for Windows and is left out there; the local web process runs without it.
- On Windows PCs with an ARM processor the installer also uses the x64 Python (Windows emulates it), because `pyarrow`
  (needed for BAFU 2026) has no prebuilt packages for Windows on ARM.
- `pack_windows.sh` sets Windows line endings (CRLF) and gives `install.ps1` a UTF-8 marker (BOM); otherwise
  PowerShell 5.1 reads umlauts wrongly.
- Brightway projects are in `%LOCALAPPDATA%\pylca\Brightway3`.
- It has been checked that all packages of the lock file resolve to prebuilt packages for Windows x64. The package has
  not been tested on as many real Windows PCs as the macOS one.

### Linux

Files are in `linux/`.

- **install.sh** works like the macOS installer: it downloads `uv` 0.9.5 from GitHub (fixed checksum, x86_64 or
  aarch64) and, with it, its own Python 3.12 and the packages of `requirements-lock.txt`, all only into the unpacked
  folder (no root password, no system Python, no PATH, no shell profile). The fallback to `requirements-app.txt` works
  as on macOS. It needs curl or wget and a glibc-based distribution (not Alpine).
- **start.sh** starts the app on port 8787 and opens the browser (`xdg-open`). Closing the terminal stops it.
- At the end the installer adds a menu entry **LCA Wrench** with the logo
  (`~/.local/share/applications/lca-wrench.desktop`, read by GNOME, KDE, Xfce and others). It runs `start.sh` in a
  terminal.
- The package is a `.tar.gz`, which keeps the execute bits of the two scripts.
- Brightway projects are in `~/.local/share/Brightway3`.
- Tested with a fresh installation and an update on Ubuntu 26.04 (x86_64), and a fresh installation on Debian 12,
  Ubuntu 22.04, Fedora 41 and Arch Linux (containers). aarch64 has not been tested.

### Building the packages

```bash
./pack_mac.sh        # builds dist/LCA-Wrench-Mac.zip from the committed state
./pack_windows.sh    # builds dist/LCA-Wrench-Windows.zip from the committed state
./pack_linux.sh      # builds dist/LCA-Wrench-Linux.tar.gz from the committed state
```

Without further settings `pack_mac.sh` builds an unsigned package (the plain folder). For the signed and notarized
installer app it needs a "Developer ID Application" certificate in the keychain and a notarytool profile, stored once:

```bash
xcrun notarytool store-credentials <profile> --apple-id <apple-id> --team-id <team-id>   # asks for an app-specific password
LCA_WRENCH_SIGN_IDENTITY="Developer ID Application: <name> (<team-id>)" LCA_WRENCH_NOTARY_PROFILE=<profile> ./pack_mac.sh
```

The script signs the app with the hardened runtime, submits it to Apple, waits for the result (a few minutes),
staples the ticket and zips the app. With only `LCA_WRENCH_SIGN_IDENTITY` it is signed but not notarized, and other
Macs still block it. The identity and the profile are passed through the environment only; nothing personal is
stored in the repository.

### Checksums

`requirements-lock.txt` holds the SHA-256 checksum of every file of every package (macOS, Windows and Linux,
including the sentier-brightway archive from GitHub). All installers install with `uv pip install --require-hashes`: a file whose
checksum does not match is not installed, and the installation stops with a message instead of falling back. Only
versions that do not fit the computer at all fall back to `requirements-app.txt`, which has no checksums. The uv
download itself is checked against a fixed checksum in the installers; the Python that uv loads is not covered by the
lock file. `tests/test_lock.py` checks that every package has its checksums.

### Regenerating the lock file

After changing package versions (uv 0.9.5, as in the installers):

```bash
grep -v '^#' requirements-lock.txt | grep -v '^\s*--hash' | sed 's/ *\\$//' > pins.txt
uv pip compile pins.txt --universal --python-version 3.12 --generate-hashes --no-annotate --no-header -o lock.txt
```

Then put the four comment lines from the top of `requirements-lock.txt` before the new content.

## From source

macOS and Linux:

```bash
git clone https://github.com/lca-wrench/lca-wrench.git
cd lca-wrench
python3.12 -m venv .venv             # Windows: py -3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python setup_daten.py      # downloads the free BAFU 2025 data (about 62 MB) into a Brightway project
.venv/bin/python -m lca_wrench       # http://127.0.0.1:8787
```

Windows: the same, with `.venv\Scripts\python` instead of `.venv/bin/python`.

Options: `python -m lca_wrench --port 8790 --no-browser`. On macOS `./start.sh` still works.

`setup_daten.py` downloads the BAFU template and creates the two derived methods in the project `bafu-2025` (see
[data.md](data.md)). It does not touch other projects.

### Projects

The app shows all Brightway projects in the default Brightway folder (`~/Library/Application Support/Brightway3` on
macOS). A project with ecoinvent can be selected at the top; its databases stay unchanged. At start the app opens the
project last chosen in the app, otherwise `bafu-2025`, otherwise none: then the start page shows the project selection.
With `LCA_WRENCH_PROJECT=<name>` it starts directly in a given project. Without a BAFU project only the example model
and the two derived methods are missing.

### Log file

With `LCA_WRENCH_LOG=<file>` (the macOS and Windows start scripts set `lca-wrench.log` in their folder), errors, the
version, the Brightway folder and package versions are written to a file that can be attached to a bug report.

### Optional: faster factorization

Without `scikit-umfpack`, scipy factorizes the matrix more slowly (this only affects the start). For large databases,
`scikit-umfpack` can be installed (on macOS it needs `brew install suite-sparse swig`); bw2calc and scipy then use it
automatically. This has not been tested here.
