# Release checklist

What to check before a release. Each step that leaves this computer (push, pull request, tag, release, upload) is
decided separately; nothing here runs by itself.

## Version and dates

- [ ] The version is the same in `lca_wrench/__init__.py`, `pyproject.toml`, `CITATION.cff`, `README.md` (two places)
  and the newest heading of `CHANGELOG.md`. `tests/test_release_metadata.py` checks this.
- [ ] `date-released` in `CITATION.cff` is the day of the release. GitHub and Zenodo read it for the citation.
- [ ] `CHANGELOG.md` lists everything since the last release.

## Checks

- [ ] The GitHub workflow `test` ([ci.md](ci.md)) is green on the release commit: installation from the packages,
  the known result, ruff and all tests (browser tests in Chromium, on macOS also WebKit) and the update from the last
  release, on Linux, Windows and macOS. Locally, `./check.sh` runs lint and tests.
- [ ] For a large release only (new Brightway version, installers, calculation engine, import sources, a major
  feature): Stephan's manual test with real data, see "Manual tests" in [ci.md](ci.md).
- [ ] `scripts/validate.py` has run on the release on macOS, and its report is in `docs/validation.md`.

## Packages

- [ ] `pack_mac.sh` (signed and notarized), `pack_linux.sh` and `pack_windows.sh` built from the release commit. The
  CI installs and updates the unsigned packages on each system; the signed Mac installer app with its dialogs is tried
  by hand.

## Open for 0.1.1 (as of 2026-11-22)

- `CITATION.cff` says `date-released: "2026-11-21"`. That was the planned date, and no release happened that day: set it
  to the actual day.
- `docs/validation.md`: the macOS row and column of 0.1.1 are marked TODO (the run passed, its report is not in the
  repository yet).
- `lca_wrench/premise-requirements.txt` still pins bw2data 4.7 (the app uses 4.8); see
  `notes/2026-11-22-bw2data-4.8-fuer-stephan.md`.
- The UI changes on the branch `z2/ui-polish` are not in `CHANGELOG.md` yet: add them under 0.1.1 or under the next
  version, depending on which release they go into. The branch builds on `z2/windows-lock-fix`.
