"""Tests for stat transformation and orchestration helpers."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from nfl_sleeper_stats import get_stats


def frame_records(frame: Any) -> list[dict[str, object]]:
    """Return DataFrame rows as plain dictionaries for assertions."""
    if hasattr(frame, "to_dicts"):
        return frame.to_dicts()
    return frame.to_dict(orient="records")


def frame_column_values(frame: Any, column: str) -> list[object]:
    """Return a column as a plain Python list."""
    if hasattr(frame, "get_column"):
        return frame.get_column(column).to_list()
    return frame[column].tolist()


def make_frame(rows: list[dict[str, object]], columns: list[str] | None = None) -> Any:
    """Build a DataFrame that matches the library used by the module under test."""
    frame = get_stats.pl.DataFrame(rows)
    return frame.select(columns) if columns else frame


def make_players_frame(rows: list[dict[str, object]]) -> Any:
    """Build a player DataFrame for tests."""
    return make_frame(rows, columns=get_stats.PLAYER_COLUMNS)


def make_players_index(rows: list[dict[str, object]]) -> get_stats.PlayerIndex:
    """Build a player index for tests."""
    return get_stats.build_player_index(make_players_frame(rows))


def test_parse_args_uses_expected_defaults() -> None:
    """Use the documented default CLI values when no flags are provided."""
    args = get_stats.parse_args([])

    assert args.start_year == 2009
    assert args.end_year == date.today().year
    assert args.force_refresh is False


def test_parse_args_accepts_custom_values() -> None:
    """Accept explicit CLI overrides for years and force-refresh."""
    args = get_stats.parse_args(["--start-year", "2014", "--end-year", "2015", "--force-refresh"])

    assert args.start_year == 2014
    assert args.end_year == 2015
    assert args.force_refresh is True


def test_main_dispatches_cli_args_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parse CLI flags and forward the resolved values into the runner."""
    captured: dict[str, object] = {}

    def fake_run(*, start_year: int, end_year: int, force_refresh: bool) -> None:
        captured["start_year"] = start_year
        captured["end_year"] = end_year
        captured["force_refresh"] = force_refresh

    monkeypatch.setattr(get_stats, "run", fake_run)

    get_stats.main(["--start-year", "2012", "--end-year", "2013", "--force-refresh"])

    assert captured == {
        "start_year": 2012,
        "end_year": 2013,
        "force_refresh": True,
    }


def test_build_player_index_groups_players_by_position_and_string_id() -> None:
    """Normalize player IDs to strings and group lookups by position once per run."""
    player_index = get_stats.build_player_index(
        make_frame(
            [
                {"player_id": 1, "name": "Pat Pass", "position": "QB", "team": "KC"},
                {"player_id": "alpha", "name": "Will Wide", "position": "WR", "team": "SF"},
            ],
            columns=get_stats.PLAYER_COLUMNS,
        )
    )

    assert player_index["QB"] == {"1": {"name": "Pat Pass", "position": "QB", "team": "KC"}}
    assert player_index["WR"] == {"alpha": {"name": "Will Wide", "position": "WR", "team": "SF"}}


def test_run_uses_end_year_as_an_exclusive_upper_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process seasons up to, but not including, the configured end-year."""
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class FakeStats:
        def get_all_stats(self, season_type: str, season: int) -> dict[str, dict[str, float]]:
            assert season_type == get_stats.SEASON_TYPE
            assert season == 2024
            return {"1": {"rank_std": 1, "pass_att": 300.0}}

        def get_all_projections(self, season_type: str, season: int) -> dict[str, dict[str, float]]:
            assert season_type == get_stats.SEASON_TYPE
            assert season == 2024
            return {}

    def fake_read_write_data(
        data_name: str,
        func: object,
        *args: object,
        **kwargs: object,
    ) -> Any:
        calls.append((data_name, args, kwargs))
        if data_name == "all_players":
            return make_players_frame(
                [{"player_id": "1", "name": "Pat Pass", "position": "QB", "team": "KC"}]
            )
        return make_frame([{"rank_std": 1.0}])

    monkeypatch.setattr(get_stats, "Stats", FakeStats)
    monkeypatch.setattr(get_stats, "read_write_data", fake_read_write_data)
    monkeypatch.setattr(get_stats, "POSITIONS", ["QB", "DEF"])

    get_stats.run(start_year=2024, end_year=2025, force_refresh=False)

    assert [name for name, _, _ in calls] == [
        "all_players",
        "2024_QB_stats",
        "2024_DEF_stats",
        "QB_stats",
        "DEF_stats",
    ]
    assert calls[0][2]["force_refresh"] is False
    assert calls[1][2]["force_refresh"] is False
    assert calls[3][2]["force_refresh"] is True
    assert calls[4][2]["force_refresh"] is True


def test_run_fetches_projections_and_passes_them_to_season_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fetch season projections once and forward them into season row generation."""
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class FakeStats:
        def get_all_stats(self, season_type: str, season: int) -> dict[str, dict[str, float]]:
            assert season_type == get_stats.SEASON_TYPE
            assert season == 2024
            return {"1": {"pass_att": 300.0, "rank_std": 1.0}}

        def get_all_projections(self, season_type: str, season: int) -> dict[str, dict[str, float]]:
            assert season_type == get_stats.SEASON_TYPE
            assert season == 2024
            return {"1": {"adp_ppr": 12.0, "adp_half_ppr": 11.0}}

    def fake_read_write_data(
        data_name: str,
        func: object,
        *args: object,
        **kwargs: object,
    ) -> Any:
        calls.append((data_name, args, kwargs))
        if data_name == "all_players":
            return make_players_frame(
                [{"player_id": "1", "name": "Pat Pass", "position": "QB", "team": "KC"}]
            )
        return make_frame([{"rank_std": 1.0}])

    monkeypatch.setattr(get_stats, "Stats", FakeStats)
    monkeypatch.setattr(get_stats, "read_write_data", fake_read_write_data)
    monkeypatch.setattr(get_stats, "POSITIONS", ["QB"])

    get_stats.run(start_year=2024, end_year=2025, force_refresh=False)

    assert calls[1][0] == "2024_QB_stats"
    assert calls[1][1][4] == {"1": {"adp_ppr": 12.0, "adp_half_ppr": 11.0}}


def test_get_all_players_filters_supported_positions_and_builds_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep only supported positions and derive names consistently."""

    class FakePlayers:
        def get_all_players(self) -> dict[str, dict[str, object]]:
            return {
                "2": {
                    "player_id": "2",
                    "full_name": "Pat Pass",
                    "position": "QB",
                    "team": "KC",
                },
                "alpha": {
                    "player_id": "alpha",
                    "first_name": "Will",
                    "last_name": "Wide",
                    "position": "WR",
                    "team": "SF",
                },
                "3": {
                    "player_id": "3",
                    "full_name": "Sam Safety",
                    "position": "S",
                    "team": "DEN",
                },
            }

    monkeypatch.setattr(get_stats, "Players", FakePlayers)

    records = frame_records(get_stats.get_all_players())

    assert [record["name"] for record in records] == ["Will Wide", "Pat Pass"]
    assert [record["position"] for record in records] == ["WR", "QB"]
    assert [record["team"] for record in records] == ["SF", "KC"]
    assert [str(record["player_id"]) for record in records] == ["alpha", "2"]


def test_remap_team_abbr_in_stats_rewrites_legacy_keys() -> None:
    """Replace legacy defense keys with the modern team abbreviations."""
    stats = {"OAK": {"pts_std": 10}, "SD": {"pts_std": 8}, "KC": {"pts_std": 7}}

    remapped = get_stats.remap_team_abbr_in_stats(stats)

    assert remapped == {"LV": {"pts_std": 10}, "LAC": {"pts_std": 8}, "KC": {"pts_std": 7}}


def test_create_season_stats_dict_uses_season_specific_qualification_thresholds() -> None:
    """Apply the 16-game and 17-game thresholds according to season."""
    players_index = make_players_index(
        [{"player_id": "1", "name": "Pat Pass", "position": "QB", "team": "KC"}]
    )["QB"]
    raw_stats = {"1": {"pass_att": 224.0, "rank_std": 4.0}}

    season_2020 = get_stats.create_season_stats_dict(players_index, raw_stats, 2020, "QB")
    season_2021 = get_stats.create_season_stats_dict(players_index, raw_stats, 2021, "QB")

    assert list(season_2020) == ["1"]
    assert season_2021 == {}


def test_create_season_stats_dict_allows_defense_without_volume_thresholds() -> None:
    """Include defense rows even when player thresholds do not apply."""
    players_index = make_players_index(
        [{"player_id": "LV", "name": "Raiders DEF", "position": "DEF", "team": "LV"}]
    )["DEF"]

    season_stats = get_stats.create_season_stats_dict(players_index, {"LV": {}}, 2024, "DEF")

    assert season_stats == {
        "LV": {
            "name": "Raiders DEF",
            "position": "DEF",
            "team": "LV",
            "stats": {},
        }
    }


def test_get_position_stats_returns_sorted_unique_stats() -> None:
    """Collect unique stat names in a stable sorted order."""
    season_stats = {
        "1": {"stats": {"rush_td": 1.0, "rank_std": 3.0}},
        "2": {"stats": {"rank_std": 2.0, "pass_yd": 275.0}},
    }

    assert get_stats.get_position_stats(season_stats) == ["pass_yd", "rank_std", "rush_td"]


def test_create_season_player_list_fills_missing_and_none_stats() -> None:
    """Default missing and null stat values to zero in season output rows."""
    season_stats = {
        "1": {
            "name": "Pat Pass",
            "position": "QB",
            "team": "KC",
            "stats": {"pass_yd": None, "rank_std": 2.0},
        }
    }

    player_rows = get_stats.create_season_player_list(
        2024,
        season_stats,
        ["pass_yd", "rank_std", "rush_yd"],
    )

    assert player_rows == [
        {
            "player_id": "1",
            "name": "Pat Pass",
            "position": "QB",
            "team": "KC",
            "season": 2024,
            "pass_yd": 0.0,
            "rank_std": 2.0,
            "rush_yd": 0.0,
        }
    ]


def test_get_season_stats_sorts_rows_by_rank_std() -> None:
    """Return season rows ordered by ascending standard rank."""
    players_index = make_players_index(
        [
            {"player_id": "1", "name": "Pat Pass", "position": "QB", "team": "KC"},
            {"player_id": "2", "name": "Alex Arm", "position": "QB", "team": "BUF"},
        ]
    )["QB"]
    raw_stats = {
        "1": {"pass_att": 300.0, "rank_std": 2.0},
        "2": {"pass_att": 320.0, "rank_std": 1.0},
    }

    season_frame = get_stats.get_season_stats(players_index, raw_stats, 2024, "QB")

    assert [record["name"] for record in frame_records(season_frame)] == ["Alex Arm", "Pat Pass"]


def test_get_season_stats_merges_selected_adp_projection_fields() -> None:
    """Attach the selected ADP ranks from season projections to each matched player row."""
    players_index = make_players_index(
        [{"player_id": "1", "name": "Pat Pass", "position": "QB", "team": "KC"}]
    )["QB"]
    raw_stats = {"1": {"pass_att": 300.0, "rank_std": 2.0}}
    raw_projections = {
        "1": {
            "adp_2qb": 10.0,
            "adp_dynasty": 11.0,
            "adp_dynasty_2qb": 12.0,
            "adp_dynasty_half_ppr": 13.0,
            "adp_dynasty_ppr": 14.0,
            "adp_half_ppr": 15.0,
            "adp_ppr": 16.0,
            "adp_std": 17.0,
            "pts_std": 999.0,
        }
    }

    season_frame = get_stats.get_season_stats(players_index, raw_stats, 2024, "QB", raw_projections)

    assert frame_records(season_frame) == [
        {
            "player_id": "1",
            "name": "Pat Pass",
            "position": "QB",
            "team": "KC",
            "season": 2024,
            "adp_2qb": 10.0,
            "adp_dynasty": 11.0,
            "adp_dynasty_2qb": 12.0,
            "adp_dynasty_half_ppr": 13.0,
            "adp_dynasty_ppr": 14.0,
            "adp_half_ppr": 15.0,
            "adp_ppr": 16.0,
            "pass_att": 300.0,
            "rank_std": 2.0,
        }
    ]


def test_create_week_stats_dict_filters_by_requested_position() -> None:
    """Only include matching-position rows in weekly dictionaries."""
    players_index = make_players_index(
        [
            {"player_id": "1", "name": "Pat Pass", "position": "QB", "team": "KC"},
            {"player_id": "2", "name": "Ron Run", "position": "RB", "team": "SF"},
        ]
    )["QB"]

    week_stats = get_stats.create_week_stats_dict(
        players_index,
        {"1": {"pass_td": 2.0}, "2": {"rush_td": 1.0}},
        "QB",
    )

    assert week_stats == {
        "1": {
            "name": "Pat Pass",
            "position": "QB",
            "team": "KC",
            "stats": {"pass_td": 2.0},
        }
    }


def test_create_week_player_list_fills_missing_stats() -> None:
    """Default absent weekly stat values to zero."""
    week_stats = {
        "1": {
            "name": "Pat Pass",
            "position": "QB",
            "team": "KC",
            "stats": {"pass_td": 2.0},
        }
    }

    player_rows = get_stats.create_week_player_list(2024, 3, week_stats, ["pass_td", "rush_td"])

    assert player_rows == [
        {
            "player_id": "1",
            "name": "Pat Pass",
            "position": "QB",
            "team": "KC",
            "season": 2024,
            "week": 3,
            "pass_td": 2.0,
            "rush_td": 0.0,
        }
    ]


def test_get_week_stats_sets_player_id_index() -> None:
    """Expose weekly rows with player_id preserved as a regular data column."""
    players_index = make_players_index(
        [{"player_id": "1", "name": "Pat Pass", "position": "QB", "team": "KC"}]
    )["QB"]

    week_frame = get_stats.get_week_stats(
        players_index,
        {"1": {"pass_td": 2.0}},
        2024,
        1,
        "QB",
    )

    assert [str(value) for value in frame_column_values(week_frame, "player_id")] == ["1"]
    assert frame_records(week_frame) == [
        {
            "player_id": "1",
            "name": "Pat Pass",
            "position": "QB",
            "team": "KC",
            "season": 2024,
            "week": 1,
            "pass_td": 2.0,
        }
    ]


def test_combine_position_stats_keeps_curated_columns_and_fills_non_team_nulls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Drop unknown columns while keeping the curated stat schema intact."""
    season_frames = {
        "2020_QB_stats.csv": make_frame(
            [
                {
                    "player_id": "1",
                    "name": "Pat Pass",
                    "position": "QB",
                    "team": None,
                    "season": 2020,
                    "adp_half_ppr": 15.0,
                    "adp_ppr": 16.0,
                    "pass_yd": 250.0,
                    "bonus_pass_cmp_25": 1.0,
                    "ignored": 99.0,
                }
            ]
        ),
        "2021_QB_stats.csv": make_frame(
            [
                {
                    "player_id": "2",
                    "name": "Alex Arm",
                    "position": "QB",
                    "team": "BUF",
                    "season": 2021,
                    "adp_half_ppr": None,
                    "adp_ppr": 18.0,
                    "pass_yd": None,
                    "bonus_pass_cmp_25": 0.0,
                    "ignored": 50.0,
                }
            ]
        ),
    }

    def fake_read_df_from_csv(file_path: str) -> Any:
        return season_frames[Path(file_path).name]

    monkeypatch.setattr(get_stats, "read_df_from_csv", fake_read_df_from_csv)
    monkeypatch.setattr(get_stats, "START_YEAR", 2020)
    monkeypatch.setattr(get_stats, "END_YEAR", 2022)
    monkeypatch.setattr(get_stats.constants, "DATA_PATH", tmp_path / "data")

    combined = get_stats.combine_position_stats("QB")

    assert "ignored" not in combined.columns
    assert "bonus_pass_cmp_25" in combined.columns
    assert frame_records(combined) == [
        {
            "player_id": "1",
            "name": "Pat Pass",
            "position": "QB",
            "team": None,
            "season": 2020,
            "adp_half_ppr": 15.0,
            "adp_ppr": 16.0,
            "pass_yd": 250.0,
            "bonus_pass_cmp_25": 1.0,
        },
        {
            "player_id": "2",
            "name": "Alex Arm",
            "position": "QB",
            "team": "BUF",
            "season": 2021,
            "adp_half_ppr": 0.0,
            "adp_ppr": 18.0,
            "pass_yd": 0.0,
            "bonus_pass_cmp_25": 0.0,
        },
    ]
