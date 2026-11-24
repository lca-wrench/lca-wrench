# Automatic tests (CI)

The GitHub workflow [`.github/workflows/test.yml`](../.github/workflows/test.yml) tests every change on Linux, Windows
and macOS the way a user gets LCA Wrench: from the release package, with the installer, on the packages the installer
chooses. It runs on every pull request, on every push to `main`, and by hand (Actions → test → "Run workflow").

## What it checks

On `ubuntu-latest`, `windows-latest` and `macos-latest`:

1. **Release packages.** `pack_linux.sh` and `pack_windows.sh` build the packages of the commit (on Linux), `pack_mac.sh`
   the Mac package (on macOS, unsigned: the folder alone).
2. **Fresh installation as a user does it** (`scripts/ci_package.py install`): unpack, run `install.sh`,
   `install.ps1` or "Install LCA Wrench.command" (on macOS through `bootstrap.sh`, as the installer app does), into a
   folder outside the checkout. The installer loads uv, its own Python 3.12 and the packages of
   `requirements-lock.txt` with their checksums.
3. **Free demo data**: the BAFU 2025 template (`setup_daten.py`, 62 MB from files.brightway.dev), set up by the
   installed version in a Brightway folder of its own (`BRIGHTWAY2_DIR`). No ecoinvent, no licensed data, no secrets.
4. **Known result**: the app is started with the package's own start script, and through its HTTP API
   1 kWh "Electricity, low voltage, at grid" (CH), climate change, must give **0.0142065 kg CO2-eq** as stored and
   **0.0970550 kg CO2-eq** with completed factors (relative tolerance 1e-5; the same values as
   `tests/test_completion.py` and [validation.md](validation.md)).
5. **Lint and all tests** (`ruff`, `pytest`) on the packages of that installation, the browser tests in Chromium.
   On macOS the browser tests run a second time in **WebKit**, the engine of Safari.
6. **Update from the last release** (second job): the package of the last published release is installed (on Linux:
   v0.1.0 had no Linux package, so its app with today's Linux scripts), it sets up its data and must give the known
   result; then the package of this commit is installed over it, as the README of each package describes, and must
   give the same result on the same data.

A system that fails does not stop the others (`fail-fast: false`).

## When something fails

The run keeps for 14 days, as artifacts of the run:

- `failure-<system>`: for every browser test that failed, a screenshot of each page, a video and a Playwright trace
  (open it with `python -m playwright show-trace <file>`, or drop it on trace.playwright.dev); and the logs of the
  installation (`installation-log.txt`), of the app (`lca-wrench.log`) and of its start (`ci-server.log`).
- `update-failure-<system>`: the logs of the update test.

## Time and caches

Expected per system: about 5 minutes for the installation, 15 to 20 for the tests (Windows is the slowest), 5 for the
update test. Kept between runs: the Brightway folder with the BAFU data (per system, renewed when `setup_daten.py` or
`requirements-lock.txt` change), the downloads of the test tools, and the Playwright browsers. The installation itself
always downloads afresh, as on a user's computer.

## Manual tests: only for large releases

With these checks green, a release needs no manual test by Stephan, except for **large releases**: a new Brightway
version, changes to the installers or the calculation engine, new import sources, or a new major feature. Then, on a
real computer with real data, what the CI cannot do:

- ecoinvent: import with an account and from files, and a calculation on it (licensed data, never in the CI);
- premise scenarios (they need ecoinvent; their own environment `.premise-venv`);
- the signed and notarized Mac installer app with its dialogs (the CI runs the same `bootstrap.sh` without dialogs);
- real projects of the Activity Browser 2 and 3 (test copies, working copies, changes from outside);
- a large project (ecoinvent) for speed, and the browser on a real phone.

## Running it locally

- The same steps without GitHub, on this computer:

  ```bash
  ./pack_linux.sh
  python scripts/ci_package.py install dist/LCA-Wrench-Linux.tar.gz /tmp/try/LCA-Wrench
  export BRIGHTWAY2_DIR=/tmp/try/brightway; mkdir -p "$BRIGHTWAY2_DIR"
  python scripts/ci_package.py data /tmp/try/LCA-Wrench
  python scripts/ci_package.py start /tmp/try/LCA-Wrench --port 8801
  python scripts/ci_package.py reference --port 8801
  python scripts/ci_package.py stop /tmp/try/LCA-Wrench --port 8801
  ```

  On Linux the installer adds a menu entry; set `XDG_DATA_HOME` to a temporary folder to keep it out of the real menu.
- The browser tests in another browser: `LCA_WRENCH_BROWSER=chromium` or `webkit` (`python -m playwright install
  webkit`); `LCA_WRENCH_ARTIFACTS=<folder>` keeps trace, video and screenshot of failures (`tests/browser_support.py`).
- The workflow file: [actionlint](https://github.com/rhysd/actionlint) checks it (with shellcheck on the PATH, also
  the shell commands in it).
- The Linux jobs in Docker with [act](https://github.com/nektos/act), from a clone (not a git worktree) whose
  `origin` is the GitHub repository (the update job takes the last release from its public release pages):
  `act workflow_dispatch --matrix os:ubuntu-latest -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-24.04
  --artifact-server-path /tmp/act-artifacts --cache-server-path /tmp/act-cache`. No token is needed. act runs the
  jobs side by side on the host network, so two of them may want the same port at once; on GitHub each job has its
  own machine.
