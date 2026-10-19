import os
from pathlib import Path

import pytest

from tests import synth
from ugrc import store

PAPER = Path(os.environ.get("UGRC_TEST_PDF", Path.home() / "Downloads" / "1-s2.0-S1385894726098128-main.pdf"))


@pytest.fixture
def synth_root(tmp_path):
    return synth.make(tmp_path / "synth")


@pytest.fixture
def con(synth_root):
    c = store.connect_readonly(synth_root)
    yield c
    c.close()


@pytest.fixture(scope="session")
def paper_root(tmp_path_factory):
    if not PAPER.exists():
        pytest.skip(f"the test paper is not at {PAPER} (set UGRC_TEST_PDF)")
    root = tmp_path_factory.mktemp("paper")
    store.build(PAPER, root)
    return root
