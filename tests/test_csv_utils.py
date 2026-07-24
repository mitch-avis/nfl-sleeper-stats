"""Tests for CSV read/write helpers."""

from pathlib import Path
from typing import Any

import pytest

from nfl_sleeper_stats.utils import csv_utils


def frame_records(frame: Any) -> list[dict[str, object]]:
    """Return DataFrame rows as plain dictionaries for assertions."""
    if hasattr(frame, "to_dicts"):
        return frame.to_dicts()
    return frame.to_dict(orient="records")


def make_frame(rows: list[dict[str, object]]) -> Any:
    """Build a DataFrame that matches the library used by the module under test."""
    dataframe_module = csv_utils.pl
    return dataframe_module.DataFrame(rows)


def test_read_write_data_generates_and_caches_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generate data on a cache miss and write it to disk."""
    monkeypatch.setattr(csv_utils, "DATA_PATH", tmp_path)

    dataframe = csv_utils.read_write_data("sample", lambda: [{"value": 1.0}])

    assert frame_records(dataframe) == [{"value": 1.0}]
    assert (tmp_path / "sample.csv").is_file()


def test_read_write_data_reuses_existing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read an existing cache file instead of regenerating it."""
    monkeypatch.setattr(csv_utils, "DATA_PATH", tmp_path)
    cached_file = tmp_path / "sample.csv"
    csv_utils.write_df_to_csv(make_frame([{"value": 2.0}]), str(cached_file))

    def should_not_run() -> list[dict[str, float]]:
        raise AssertionError("generator should not be called when cache exists")

    dataframe = csv_utils.read_write_data("sample", should_not_run)

    assert frame_records(dataframe) == [{"value": 2.0}]


def test_read_df_from_csv_exits_for_missing_file(tmp_path: Path) -> None:
    """Exit with an error when a required CSV file is missing."""
    with pytest.raises(SystemExit):
        csv_utils.read_df_from_csv(str(tmp_path / "missing.csv"))


def test_read_df_from_csv_drops_the_blank_index_column(tmp_path: Path) -> None:
    """Hide the persisted CSV index column when reading cached data back in."""
    file_path = tmp_path / "sample.csv"
    file_path.write_text(",value\n0,3.0\n1,4.0\n", encoding="utf-8")

    dataframe = csv_utils.read_df_from_csv(str(file_path))

    assert frame_records(dataframe) == [{"value": 3.0}, {"value": 4.0}]


def test_write_df_to_csv_creates_parent_directories(tmp_path: Path) -> None:
    """Create missing parent directories before writing CSV output."""
    file_path = tmp_path / "nested" / "sample.csv"

    csv_utils.write_df_to_csv(make_frame([{"value": 3.0}]), str(file_path))

    assert file_path.is_file()
    assert frame_records(csv_utils.read_df_from_csv(str(file_path))) == [{"value": 3.0}]


def test_write_df_to_csv_preserves_the_blank_index_header(tmp_path: Path) -> None:
    """Write CSV files with the existing leading blank index header intact."""
    file_path = tmp_path / "sample.csv"

    csv_utils.write_df_to_csv(make_frame([{"value": 3.0}]), str(file_path))

    assert file_path.read_text(encoding="utf-8").splitlines()[0] == ",value"
