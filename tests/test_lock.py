"""The installers install with --require-hashes: every package in requirements-lock.txt needs its exact version and
SHA-256 checksums, for macOS and Windows, and Brightway stays on the versions requirements-app.txt names."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _entries():
    text = (ROOT / "requirements-lock.txt").read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    for chunk in re.split(r"\n(?=\S)", body.strip()):
        head = chunk.split("\\")[0].strip()
        yield head, re.findall(r"--hash=sha256:([0-9a-f]{64})", chunk)


def test_every_package_is_pinned_with_checksums():
    entries = list(_entries())
    assert len(entries) > 90
    for head, hashes in entries:
        assert hashes, f"no checksum: {head}"
        assert "==" in head or " @ https://" in head, f"not pinned: {head}"
    names = {re.split(r"[=@ ;]", h)[0].lower() for h, _ in entries}
    assert {"bw2data", "bw2calc", "fastapi", "sentier-brightway", "colorama"} <= names  # colorama: Windows only


def test_brightway_on_the_versions_of_the_fallback():
    pins = {re.split(r"[=@ ;]", h)[0].lower(): h.split("==")[1].split(" ")[0] for h, _ in _entries() if "==" in h}
    for line in (ROOT / "requirements-app.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([\w.-]+)==([\w.]+)$", line.strip())
        if m:
            assert pins[m.group(1).lower()] == m.group(2), line


def test_installers_require_the_checksums():
    for script in ("mac/Install LCA Wrench.command", "windows/install.ps1"):
        text = (ROOT / script).read_text(encoding="utf-8")
        assert "--require-hashes" in text and "hash mismatch" in text, script


def test_installers_refuse_the_source_tree():
    # run from a clone or "Source code (zip)" they must point to the release package (issue #1)
    # script and its first write to the folder: the check must come before it
    for script, first_write in (("mac/Install LCA Wrench.command", "mkdir -p"), ("windows/install.ps1", "New-Item")):
        text = (ROOT / script).read_text(encoding="utf-8")
        assert "releases/latest" in text and "Source code (zip)" in text, script
        assert text.index("releases/latest") < text.index(first_write), script
