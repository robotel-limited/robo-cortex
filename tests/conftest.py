import pytest


@pytest.fixture(autouse=True)
def isolated_global_store(tmp_path, monkeypatch):
    """Every test (including CLI subprocess tests, which inherit the
    parent's environment) gets its own scope-B store, never the real
    ~/.cortex/global.db on the machine running the suite -- see
    core/store.py's ROBO_CORTEX_GLOBAL_DB override.
    """
    monkeypatch.setenv("ROBO_CORTEX_GLOBAL_DB", str(tmp_path / "global.db"))
