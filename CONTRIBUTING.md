# Contributing

Bug reports and feature requests go to [GitHub Issues](https://github.com/lca-wrench/lca-wrench/issues). Code changes
are welcome as pull requests against `main`.

## Setup

```bash
git clone https://github.com/lca-wrench/lca-wrench.git
cd lca-wrench
python3.12 -m venv .venv             # Windows: py -3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install -r requirements-dev.txt   # pytest, httpx, ruff, playwright (separately: the lock file uses checksums)
.venv/bin/python setup_daten.py      # free BAFU 2025 data (about 62 MB); the tests need it
```

On Windows use `.venv\Scripts\python`. Run the app with `.venv/bin/python -m lca_wrench`.

## Tests

```bash
./check.sh                 # ruff and pytest, including the browser tests (Google Chrome)
./check.sh --no-browser    # skips the browser tests
```

Or without the script: `python -m ruff check . && python -m pytest -q`. The workflow `.github/workflows/test.yml` runs
the same on Linux, Windows and macOS for every pull request and push to `main`, after installing from the release
package as a user does (see [docs/ci.md](docs/ci.md)).

The tests never touch real projects. They need the project `bafu-2025` created by `setup_daten.py` and work in a copy,
`lca-wrench-test`, which is created on the first run. `bafu-2025` cannot be opened by a test (`set_current` raises an
error), and the registry file `lca-wrench.json` is replaced by a temporary file. See `tests/conftest.py`. Without
`bafu-2025`, the tests that need data are skipped with a message; the others (lock file, translations) still run.
The tests run with the completed factors switched off, except `tests/test_completion.py`, which checks both modes. Tests run with
German texts (`LCA_WRENCH_LANG=de`). ecoinvent data cannot be redistributed, so tests use the BAFU data and a miniature
ecoinvent-shaped database (`tests/ecoinvent_mini.py`). Add tests for changed behaviour; calculation changes need a
comparison with bw2calc or an independent calculation, as in the existing tests.

## Code style

The linter is ruff (`ruff.toml`; line length 140). `ruff check .` must pass. Code comments are in English. Keep changes
small and in scope: no unrelated refactoring or formatting changes in the same pull request. New dependencies need a
reason in the pull request and an update of `requirements-lock.txt` (see [docs/install.md](docs/install.md)).

## Texts and translation

The German text is the key; English is the default language for users.

- **Interface (JavaScript):** write `t('German text')` or `t('… {n} …', { n: 3 })`. Add the English text as one
  single-quoted entry per line in `lca_wrench/static/js/i18n.js`.
- **Server messages (Python):** write `_('German text', name=value)`, or `msg(...)` for texts that are stored and rendered
  later. Add the key and its English translation to the dict `EN` in `lca_wrench/i18n.py`.
- A text without an English entry is shown in German.

`tests/test_i18n.py` enforces that every key has an English entry with the same placeholders and that no unused interface
entry remains. Data (names of activities and methods) is not translated.

## Pull requests

Branch from `main`, keep one topic per pull request, describe what changed and how it was checked, and make sure
`./check.sh` passes. Do not include licensed data (ecoinvent) in issues, tests or pull requests.
