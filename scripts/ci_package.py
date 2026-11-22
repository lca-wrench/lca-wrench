"""Install a release package the way a user does, start and stop the installed app, and check a reference result.

Used by the GitHub workflow (.github/workflows/test.yml) on Linux, macOS and Windows; runs the same way locally.
Standard library only: it runs with any Python 3.10+, before and next to the installed one.

  python scripts/ci_package.py install <package> <folder>   fresh, or an update when <folder> holds an installation
  python scripts/ci_package.py python <folder>              the Python of the installation
  python scripts/ci_package.py data <folder> [--script F]   the free BAFU 2025 project, set up by the installed version
  python scripts/ci_package.py dev <folder>                 the test tools (requirements-dev.txt) into the installation
  python scripts/ci_package.py start <folder> [--port N]    with the package's own start script, until it answers
  python scripts/ci_package.py stop <folder> [--port N]
  python scripts/ci_package.py reference [--port N]         the known result of the BAFU 2025 data (see below)

How each package is installed and updated (as its README.txt says, "Updating to a newer version"):
- Linux: unpack LCA-Wrench-Linux.tar.gz next to the folder, run install.sh. An update first deletes the folder's
  lca_wrench (the old program code, no user data), then unpacks over it.
- Windows: the same with LCA-Wrench-Windows.zip and install.ps1.
- macOS: the signed package holds "Install LCA Wrench.app", whose bootstrap.sh copies the folder to the place chosen
  (here LCA_WRENCH_INSTALL_DIR, without the dialogs) and replaces the app code on an update; then "Install LCA
  Wrench.command" runs. An unsigned package (pack_mac.sh without a certificate) holds the folder alone; it goes
  through the same bootstrap.sh of this repository.
The scripts get no terminal (stdin is not a tty), so they do not wait for a key at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"
FOLDER = "LCA-Wrench"

# 1 kWh of Swiss low voltage electricity with the climate method LCA Wrench adds to the BAFU 2025 project
# (setup_daten.py): the method as stored, and with the completed factors (tests/test_completion.py, docs/validation.md)
REFERENCE = {"name": "Electricity, low voltage, at grid", "location": "CH", "database": "BAFU-2025-v2",
             "method": ["Werkbank", "Klimawandel", "kg CO2-eq, abgeleitet aus UBP 2021"],
             "as stored": 0.0142065, "completed": 0.0970550, "rel": 1e-5}


def log(msg: str) -> None:
    print(f"[ci_package] {msg}", flush=True)


def venv_python(folder: Path) -> Path:
    return folder / (".venv/Scripts/python.exe" if WINDOWS else ".venv/bin/python")


# ---------- install ----------

def _unpack(package: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    if package.name.endswith(".tar.gz"):
        with tarfile.open(package) as t:
            t.extractall(into, filter="tar")  # keeps the execute bits of install.sh and start.sh
    elif MAC:
        subprocess.run(["ditto", "-x", "-k", str(package), str(into)], check=True)  # keeps the signed app intact
    else:
        with zipfile.ZipFile(package) as z:
            z.extractall(into)


def install(package: Path, folder: Path) -> None:
    package, folder = package.resolve(), folder.resolve()
    update = (folder / "VERSION").is_file()
    log(f"{'update' if update else 'fresh installation'}: {package.name} -> {folder}")
    if update:
        log(f"installed before: {(folder / 'VERSION').read_text().strip()}")
    if MAC:
        with tempfile.TemporaryDirectory() as tmp:
            _unpack(package, Path(tmp))
            app = Path(tmp) / "Install LCA Wrench.app"
            if app.is_dir():
                bootstrap = app / "Contents/Resources/bootstrap.sh"
            else:  # unsigned: the folder alone, through this repository's bootstrap.sh
                res = Path(tmp) / "Resources"
                res.mkdir()
                (Path(tmp) / FOLDER).rename(res / "payload")
                bootstrap = res / "bootstrap.sh"
                shutil.copy(ROOT / "mac/installer/bootstrap.sh", bootstrap)
            env = {**os.environ, "LCA_WRENCH_INSTALL_DIR": str(folder), "LCA_WRENCH_INSTALL_NO_RUN": "1"}
            subprocess.run(["bash", str(bootstrap)], env=env, check=True, stdin=subprocess.DEVNULL)
        cmd = ["bash", str(folder / "Install LCA Wrench.command")]
    else:
        if folder.name != FOLDER:
            sys.exit(f"The folder must be called {FOLDER} (the name inside the package): {folder}")
        if update:  # the old program code goes first, so no file of the older version stays behind
            shutil.rmtree(folder / "lca_wrench", ignore_errors=True)
        _unpack(package, folder.parent)  # over the folder on an update, as the README says
        cmd = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(folder / "install.ps1")]
               if WINDOWS else ["bash", str(folder / "install.sh")])
    log("installed now: " + (folder / "VERSION").read_text().strip())
    t = time.time()
    r = subprocess.run(cmd, cwd=folder, stdin=subprocess.DEVNULL)
    log(f"installer finished after {time.time() - t:.0f} s with exit code {r.returncode}")
    if r.returncode != 0 or not venv_python(folder).is_file():
        install_log = folder / "installation-log.txt"
        if install_log.is_file():
            print(install_log.read_text(errors="replace")[-4000:])
        sys.exit("The installation failed.")


def data(folder: Path, script: Path) -> None:
    """setup_daten.py (or the one of an older version) next to the installed app, run with its Python: it imports the
    installed lca_wrench, so each version sets up the data as it did then. BRIGHTWAY2_DIR decides where."""
    folder = folder.resolve()
    shutil.copy(script, folder / "setup_daten.py")
    log(f"data in {os.environ.get('BRIGHTWAY2_DIR', '(default Brightway folder)')}")
    subprocess.run([str(venv_python(folder)), "setup_daten.py"], cwd=folder, check=True, stdin=subprocess.DEVNULL)


def dev(folder: Path) -> None:
    """pytest, ruff and playwright into the installed environment, with the uv the installer left in .tools: the tests
    then run on exactly the packages a user gets. UV_CACHE_DIR (if set) keeps the downloads for the next run."""
    folder = folder.resolve()
    uv = folder / ".tools" / ("uv.exe" if WINDOWS else "uv")
    subprocess.run([str(uv), "pip", "install", "--quiet", "--python", str(venv_python(folder)), "-r", str(ROOT / "requirements-dev.txt")],
                   check=True)


# ---------- start / stop ----------

def _get(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={"X-Lang": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _post(url: str, body: dict, timeout: float = 600):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-LCA-Wrench": "1", "X-Lang": "en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"POST {url} failed ({e.code}): {e.read().decode(errors='replace')[:2000]}")


def start(folder: Path, port: int, wait: float) -> None:
    folder = folder.resolve()
    script = ["cmd", "/c", "Start LCA Wrench.cmd"] if WINDOWS else ["bash", "Start LCA Wrench.command" if MAC else "start.sh"]
    out = open(folder / "ci-server.log", "ab")
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    proc = subprocess.Popen(script, cwd=folder, env={**os.environ, "PORT": str(port)}, stdin=subprocess.DEVNULL,
                            stdout=out, stderr=subprocess.STDOUT, **group)
    (folder / "ci-server.pid").write_text(str(proc.pid))
    url, t = f"http://127.0.0.1:{port}", time.time()
    while time.time() - t < wait:
        if proc.poll() is not None:
            print((folder / "ci-server.log").read_text(errors="replace")[-4000:])
            sys.exit(f"The start script ended with exit code {proc.returncode}.")
        try:
            _get(f"{url}/api/state", timeout=60)
            log(f"{url} answers after {time.time() - t:.0f} s")
            return
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(2)
    sys.exit(f"{url} does not answer after {wait:.0f} s.")


def stop(folder: Path, port: int) -> None:
    folder = folder.resolve()
    pid_file = folder / "ci-server.pid"
    if pid_file.is_file():
        pid = int(pid_file.read_text())
        if WINDOWS:  # the cmd window and the Python it started
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        pid_file.unlink()
    for _ in range(60):  # the port is free again
        try:
            _get(f"http://127.0.0.1:{port}/api/state", timeout=2)
            time.sleep(1)
        except (urllib.error.URLError, OSError, ValueError):
            log(f"stopped (port {port} free)")
            return
    sys.exit(f"Port {port} still answers after stopping.")


# ---------- reference result ----------

def reference(port: int, project: str) -> None:
    url, ref = f"http://127.0.0.1:{port}", REFERENCE
    st = _post(f"{url}/api/project", {"name": project})
    assert st["project"] == project, st.get("project")
    assert any(m["id"] == ref["method"] for m in st["methods"]), "the climate method of setup_daten.py is missing"
    hits = _get(f"{url}/api/search?q={urllib.parse.quote(ref['name'])}&loc=CH")
    act = next((h for h in hits if h["name"] == ref["name"] and h["location"] == ref["location"]
                and h.get("database", ref["database"]) == ref["database"]), None)
    assert act, f"{ref['name']} ({ref['location']}) not found"
    before = bool((st.get("completion") or {}).get("enabled"))
    ok = True
    try:
        for completed in (False, True):
            _post(f"{url}/api/completion", {"enabled": completed})
            score = _post(f"{url}/api/calc", {"id": act["id"], "amount": 1.0, "method": ref["method"]})["score"]
            want = ref["completed" if completed else "as stored"]
            rel = abs(score - want) / abs(want)
            good = rel <= ref["rel"]
            ok &= good
            log(f"1 kWh {ref['name']}, {ref['location']}, climate change {'with completed factors' if completed else 'as stored'}: "
                f"{score:.7g} kg CO2-eq, expected {want:.7g} (relative gap {rel:.1e}) {'OK' if good else 'WRONG'}")
    finally:
        _post(f"{url}/api/completion", {"enabled": before})
    if not ok:
        sys.exit("The reference result is wrong.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("install")
    a.add_argument("package", type=Path)
    a.add_argument("folder", type=Path)
    a = sub.add_parser("python")
    a.add_argument("folder", type=Path)
    a = sub.add_parser("dev")
    a.add_argument("folder", type=Path)
    a = sub.add_parser("data")
    a.add_argument("folder", type=Path)
    a.add_argument("--script", type=Path, default=ROOT / "setup_daten.py")
    for name in ("start", "stop"):
        a = sub.add_parser(name)
        a.add_argument("folder", type=Path)
        a.add_argument("--port", type=int, default=8787)
        if name == "start":
            a.add_argument("--wait", type=float, default=600, help="seconds until it must answer")
    a = sub.add_parser("reference")
    a.add_argument("--port", type=int, default=8787)
    a.add_argument("--project", default="bafu-2025")
    args = p.parse_args()
    if args.cmd == "install":
        install(args.package, args.folder)
    elif args.cmd == "python":
        print(venv_python(args.folder.resolve()).as_posix())  # forward slashes: Git Bash on Windows runs it too
    elif args.cmd == "data":
        data(args.folder, args.script)
    elif args.cmd == "dev":
        dev(args.folder)
    elif args.cmd == "start":
        start(args.folder, args.port, args.wait)
    elif args.cmd == "stop":
        stop(args.folder, args.port)
    else:
        reference(args.port, args.project)


if __name__ == "__main__":
    main()
