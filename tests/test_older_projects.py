"""Projects in the older Brightway 2 format (Activity Browser 2) are never opened, only copied and converted as a copy.

The older project here is a copy of the test project with the 2.5 flag removed, which is how Brightway tells them apart.
"""

from pathlib import Path

import bw2data as bd
import pytest
from bw2data.project import ProjectDataset

from conftest import TEST_PROJECT
from lca_wrench import service as s

OLD = "lca-wrench-test-ab2"


def _files(d: Path) -> dict:
    # SQLite creates -wal/-shm next to an open database; LCA Wrench never opens the original, but be explicit
    return {str(p.relative_to(d)): (p.stat().st_mtime_ns, p.stat().st_size) for p in d.rglob("*")
            if p.is_file() and not p.name.endswith(("-wal", "-shm"))}


@pytest.fixture()
def older():
    bd.projects.set_current(TEST_PROJECT)
    for name in [p.name for p in bd.projects if p.name.startswith(OLD)]:
        s.remove_project(name)
    bd.projects.copy_project(OLD, switch=False)
    ds = ProjectDataset.get(ProjectDataset.name == OLD)
    data = dict(ds.data)
    data.pop("25", None)
    ds.data = data
    ds.save()
    yield OLD
    bd.projects.set_current(TEST_PROJECT)
    for name in [p.name for p in bd.projects if p.name.startswith(OLD)]:
        s.remove_project(name)


def test_older_project_is_marked_and_never_opened(older):
    assert not s.project_is_25(older) and s.project_is_25(TEST_PROJECT)
    with pytest.raises(ValueError, match="älteres Format|ältere Format"):
        s.set_project(older)
    assert bd.projects.current == TEST_PROJECT
    assert s.pick_start_project(older) != older
    assert next(p for p in s.state()["projects"] if p["name"] == TEST_PROJECT)["legacy"] is False
    out = s.compare([{"project": older, "id": "1", "amount": 1.0}], s.CLIMATE_METHOD)
    assert out[0]["error"] and bd.projects.current == TEST_PROJECT


def test_copy_converts_only_the_copy(older):
    original_dir = bd.projects._project_dir(ProjectDataset.get(ProjectDataset.name == older))
    before = _files(original_dir)
    bd.projects.set_current(TEST_PROJECT)
    hit = [h for h in s.search("electricity low voltage", "CH") if h["unit"] == "kWh"][0]
    expected = s.unit_score(hit["id"], s.CLIMATE_METHOD)

    new = s.copy_older_project(older)

    assert new == f"{older} (LCA Wrench)" and bd.projects.current == new and s.project_is_25(new)
    assert s.unit_score(hit["id"], s.CLIMATE_METHOD) == pytest.approx(expected, rel=1e-9)
    # the original: still the older format, not a single file touched
    assert not s.project_is_25(older)
    assert _files(original_dir) == before
    with pytest.raises(ValueError, match="braucht keine Kopie"):
        s.copy_older_project(new)
    assert s.copy_older_project(older) == f"{older} (LCA Wrench 2)"  # a second copy gets the next name
