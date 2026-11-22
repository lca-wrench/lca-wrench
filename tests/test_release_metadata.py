"""The version and the citation data agree everywhere a release names them (see docs/release-checklist.md)."""

import datetime
import re
import tomllib
from pathlib import Path

import lca_wrench

ROOT = Path(__file__).resolve().parent.parent


def cff(key: str) -> str:
    m = re.search(rf'^{key}:\s*"?([^"\n]+)"?\s*$', (ROOT / "CITATION.cff").read_text(encoding="utf-8"), re.M)
    assert m, f"CITATION.cff has no {key}"
    return m.group(1)


def test_one_version_everywhere():
    v = lca_wrench.__version__
    assert tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == v
    assert cff("version") == v
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Version {v}." in readme and f"(version {v})" in readme
    # the newest entry of the changelog is this version
    assert re.search(r"^## (\S+)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M).group(1) == v


def test_citation_date_is_a_real_date():
    # set to the day of the release (Zenodo and GitHub read it); a valid date, not in a distant future
    d = datetime.date.fromisoformat(cff("date-released"))
    assert datetime.date(2026, 1, 1) <= d <= datetime.date.today() + datetime.timedelta(days=60)
