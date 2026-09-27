"""Production notes must never be opened by a test process."""
import pytest


@pytest.fixture(autouse=True)
def isolated_notes_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTES_DATA_DIRECTORY", str(tmp_path / "app-notes"))
