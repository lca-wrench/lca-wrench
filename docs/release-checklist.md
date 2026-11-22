# Release checklist

What to check before a release. Each step that leaves this computer (push, pull request, tag, release, upload) is
decided separately; nothing here runs by itself.

## Version and dates

- [ ] The version is the same in `lca_wrench/__init__.py`, `pyproject.toml`, `CITATION.cff`, `README.md` (two places)
  and the newest heading of `CHANGELOG.md`. `tests/test_release_metadata.py` checks this.
- [ ] `date-released` in `CITATION.cff` is the day of the release. GitHub and Zenodo read it for the citation.
- [ ] `CHANGELOG.md` lists everything since the last release.

## Checks

- [ ] `./check.sh` (ruff and all tests, including the browser tests) passes on macOS, Linux and Windows. The GitHub
  workflow `.github/workflows/check.yml` runs on all three.
- [ ] `scripts/validate.py` has run on the release on macOS, and its report is in `docs/validation.md`.

## Packages

- [ ] `pack_mac.sh`, `pack_linux.sh` and `pack_windows.sh` built from the release commit, and each installer tried once
  on its system.

## Open for 0.1.1 (as of 2026-11-22)

- `CITATION.cff` says `date-released: "2026-11-21"`. That was the planned date, and no release happened that day: set it
  to the actual day.
- `docs/validation.md`: the macOS row and column of 0.1.1 are marked TODO (the run passed, its report is not in the
  repository yet).
- `lca_wrench/premise-requirements.txt` still pins bw2data 4.7 (the app uses 4.8); see
  `notes/2026-11-22-bw2data-4.8-fuer-stephan.md`.
- The UI changes on the branch `z2/ui-polish` are not in `CHANGELOG.md` yet: add them under 0.1.1 or under the next
  version, depending on which release they go into. The branch builds on `z2/windows-lock-fix`.
