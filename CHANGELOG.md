# Changelog

## 0.1.1

**Monte Carlo results with the same seed differ from 0.1.0.** This is intended: in 0.1.0 every database got the same
random draws, so uncertain values in separate models were perfectly correlated, and comparing two alternatives
("A better than B") was wrong. Deterministic results (scores, contributions, inventories) are unchanged.

### Fixes

- **Monte Carlo**: each resource group draws with its own seed, derived reproducibly from the run seed. Separate models
  are now independent; values both share (the background) stay common to them.
- **Windows**: deleting a project or a background database failed with "WinError 32" because the calculation cache
  kept its processed files open. The cleanup after a failed import or test copy left a half-deleted project behind, and
  a new one of the same name failed with "Project directory already exists". Files are now closed first, folders are
  removed with retries, and a folder left over by 0.1.0 no longer blocks a new copy. On Windows, opening a project also
  releases the files of the projects opened before, so the Activity Browser can delete or change them.
- **Imports**: premise and EXIOBASE imports no longer drop or delete models created while they run.
- **Working copies** keep the background choice of their original, and a copy that reuses the name of a deleted one
  is not served from that copy's cached results.
- **Amount set to 0** removes its uncertainty distribution (a lognormal kept sampling around the old amount); undo
  restores it.
- **Installers**: started from the source code (a clone or "Source code (zip)"), the macOS and Windows installers now
  say so and point to the release packages instead of failing with a misleading network error (#1).
- **`scripts/validate.py`** works again: it sends the header the stricter origin check requires.

### Security

- Brightway bw2data 4.8 with deepdiff 8.6.2 (CVE-2025-58367, CVE-2026-33155). LCA Wrench did not use the affected code
  path (bw2data revisions), but the packages shipped the vulnerable version. Results are unchanged.
- Stricter check that requests come from LCA Wrench itself: the full origin including the port must match, and
  changes need the app's own header.

### New

- **Linux installer**: `LCA-Wrench-Linux.tar.gz` with `install.sh` and `start.sh`, as on macOS: its own Python 3.12
  and checked packages inside the folder, no root password, a menu entry "LCA Wrench". Tested on Ubuntu 26.04 and
  22.04, Debian 12, Fedora 41 and Arch Linux (x86_64).
- **Tests on Windows and macOS**: the GitHub workflow runs lint and all tests on Ubuntu, Windows and macOS.

### Other

- Faster background builds: production amounts are read in one vectorized step (results identical).

Download `LCA-Wrench-Mac.zip`, `LCA-Wrench-Windows.zip` or `LCA-Wrench-Linux.tar.gz` from the release page.
"Source code" is not the installer.

## 0.1.0

First public release.
