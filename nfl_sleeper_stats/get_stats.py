"""Fetch, transform, and aggregate NFL Sleeper statistics.

This module builds season and combined-position CSV outputs from Sleeper API data.
"""

import argparse
from collections.abc import Mapping, Sequence
from datetime import date
from typing import TypedDict

import polars as pl
import polars.selectors as cs
from sleeper_wrapper import Players, Stats

from nfl_sleeper_stats import constants
from nfl_sleeper_stats.utils.csv_utils import read_df_from_csv, read_write_data
from nfl_sleeper_stats.utils.logger import log

START_YEAR = 2009
END_YEAR = date.today().year
SEASON_TYPE = "regular"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
PLAYER_COLUMNS = ["player_id", "name", "position", "team"]
PLAYER_SCHEMA = {
    "player_id": pl.String,
    "name": pl.String,
    "position": pl.String,
    "team": pl.String,
}
TEAM_ABBR_MAP = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}


class PlayerMetadata(TypedDict):
    """Normalized player metadata used for season and week lookups."""

    name: str
    position: str
    team: str | None


PositionPlayerIndex = Mapping[str, PlayerMetadata]
PlayerIndex = dict[str, dict[str, PlayerMetadata]]


def _player_id_sort_key(player_id: str) -> tuple[bool, int | str]:
    """Return a stable sort key for mixed Sleeper player identifiers."""
    return (player_id.isdigit(), int(player_id) if player_id.isdigit() else player_id)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the stats puller."""
    parser = argparse.ArgumentParser(description="Fetch and cache NFL Sleeper stats.")
    parser.add_argument(
        "--start-year",
        type=int,
        default=START_YEAR,
        help="First NFL season year to process.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=END_YEAR,
        help="Exclusive upper bound for NFL season years to process.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Regenerate cached CSV files instead of reusing existing ones.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the stats puller."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start_year >= args.end_year:
        parser.error("--start-year must be less than --end-year")
    return args


def main(argv: Sequence[str] | None = None) -> None:
    """Parse CLI arguments and run the requested stats pull."""
    args = parse_args(argv)
    run(
        start_year=args.start_year,
        end_year=args.end_year,
        force_refresh=args.force_refresh,
    )


def run(
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    force_refresh: bool = False,
) -> None:
    """Fetch and cache stats for all supported positions.

    Args:
        start_year: First NFL season year to process.
        end_year: Exclusive upper bound for NFL season years to process.
        force_refresh: Whether to regenerate cached CSV files.

    """
    resolved_start_year = START_YEAR if start_year is None else start_year
    resolved_end_year = END_YEAR if end_year is None else end_year

    all_players_df = read_write_data("all_players", get_all_players, force_refresh=force_refresh)
    player_index = build_player_index(all_players_df)
    stats = Stats()
    for season in range(resolved_start_year, resolved_end_year):
        raw_season_stats = stats.get_all_stats(SEASON_TYPE, season)
        raw_season_stats = remap_team_abbr_in_stats(raw_season_stats)
        raw_season_projections = stats.get_all_projections(SEASON_TYPE, season)
        raw_season_projections = remap_team_abbr_in_stats(raw_season_projections)
        for position in POSITIONS:
            season_stats_name = f"{season}_{position}_stats"
            season_stats_df = read_write_data(
                season_stats_name,
                get_season_stats,
                player_index[position],
                raw_season_stats,
                season,
                position,
                raw_season_projections,
                force_refresh=force_refresh,
            )
            log.debug("%s - %s:\n%s", season, position, season_stats_df)

        # for week in range(1, 19):
        #     if season < 2021 and week == 18:
        #         break
        #     raw_week_stats = stats.get_week_stats(SEASON_TYPE, season, str(week))
        #     week_stats_name = f"{season}_Week_{week}_DEF_Stats"
        #     week_stats_df = read_write_data(
        #         week_stats_name,
        #         get_week_stats,
        #         player_index["DEF"],
        #         raw_week_stats,
        #         season,
        #         week,
        #         "DEF",
        #         force_refresh=force_refresh,
        #     )
        #     log.debug("%s - Week %s - DEF:\n%s", season, week, week_stats_df)

    for position in POSITIONS:
        # Combined outputs depend on the requested season window, so always rebuild them.
        read_write_data(
            f"{position}_stats",
            combine_position_stats,
            position,
            resolved_start_year,
            resolved_end_year,
            force_refresh=True,
        )


def get_all_players() -> pl.DataFrame:
    """Get all supported players and return them as a Polars DataFrame.

    Returns:
        pl.DataFrame: DataFrame containing all supported players.

    """
    players = Players()
    all_players = players.get_all_players()
    players_list: list[dict[str, str | None]] = []
    for player in all_players.values():
        player_position = player.get("position")
        if player_position in POSITIONS:
            player_id = str(player.get("player_id"))
            if "full_name" in player:
                player_name = player.get("full_name")
            else:
                first_name = player.get("first_name")
                last_name = player.get("last_name")
                player_name = f"{first_name} {last_name}"

            players_list.append(
                {
                    "player_id": player_id,
                    "name": player_name,
                    "position": player_position,
                    "team": player.get("team"),
                }
            )

    players_list.sort(key=lambda player: _player_id_sort_key(player["player_id"] or ""))
    return pl.DataFrame(players_list, schema=PLAYER_SCHEMA)


def build_player_index(all_players_df: pl.DataFrame) -> PlayerIndex:
    """Index player metadata by position and player ID for fast lookups.

    Args:
        all_players_df: DataFrame containing all supported players.

    Returns:
        PlayerIndex: Nested lookup of position -> player_id -> player metadata.

    """
    player_index: PlayerIndex = {position: {} for position in POSITIONS}
    for row in all_players_df.select(PLAYER_COLUMNS).iter_rows(named=True):
        player_id = str(row["player_id"])
        position = str(row["position"])
        if position in player_index:
            player_index[position][player_id] = {
                "name": str(row["name"]),
                "position": position,
                "team": None if row["team"] is None else str(row["team"]),
            }
    return player_index


def remap_team_abbr_in_stats(stats_dict: dict) -> dict:
    """Remap legacy defense abbreviations in the stats dictionary.

    Args:
        stats_dict: Dictionary containing player statistics with team abbreviations.

    Returns:
        dict: Stats dictionary with legacy defense abbreviations normalized.

    """
    for player_id in list(stats_dict.keys()):
        if player_id in TEAM_ABBR_MAP:
            new_id = TEAM_ABBR_MAP[player_id]
            stats_dict[new_id] = stats_dict[player_id]
            del stats_dict[player_id]
    return stats_dict


def get_player_adp_ranks(
    raw_season_projections: Mapping[str, Mapping[str, object]] | None,
    player_id: str,
) -> dict[str, float]:
    """Return the selected ADP ranks for a player from the season projections payload."""
    if raw_season_projections is None:
        return {}

    player_projection = raw_season_projections.get(player_id)
    if not isinstance(player_projection, Mapping):
        return {}

    adp_ranks: dict[str, float] = {}
    for adp_field in constants.ADP_RANK_FIELDS:
        adp_value = player_projection.get(adp_field)
        if isinstance(adp_value, int | float | str):
            adp_ranks[adp_field] = float(adp_value)
    return adp_ranks


def get_season_stats(
    position_players: PositionPlayerIndex,
    raw_season_stats: dict,
    season: int,
    position: str,
    raw_season_projections: Mapping[str, Mapping[str, object]] | None = None,
) -> pl.DataFrame:
    """Get season stats for a given position and return them as a DataFrame.

    Args:
        position_players: Player metadata indexed by player ID for the requested position.
        raw_season_stats: Dictionary containing raw season stats.
        season: The season year.
        position: The position to filter stats by.
        raw_season_projections: Dictionary containing raw season projections.

    Returns:
        pl.DataFrame: DataFrame containing season stats for the given position.

    """
    season_stats_dict = create_season_stats_dict(
        position_players,
        raw_season_stats,
        season,
        position,
        raw_season_projections,
    )
    position_stats_list = get_position_stats(season_stats_dict)
    season_player_stats_list = create_season_player_list(
        season, season_stats_dict, position_stats_list
    )
    if not season_player_stats_list:
        return pl.DataFrame()

    season_player_stats_df = pl.DataFrame(season_player_stats_list)
    if "rank_std" in season_player_stats_df.columns:
        season_player_stats_df = season_player_stats_df.sort("rank_std")
    return season_player_stats_df


def create_season_stats_dict(
    position_players: PositionPlayerIndex,
    raw_season_stats: dict,
    season: int,
    position: str,
    raw_season_projections: Mapping[str, Mapping[str, object]] | None = None,
) -> dict:
    """Create a dictionary of season stats for a given position.

    Args:
        position_players: Player metadata indexed by player ID for the requested position.
        raw_season_stats: Dictionary containing raw season stats.
        season: The season year.
        position: The position to filter stats by.
        raw_season_projections: Dictionary containing raw season projections.

    Returns:
        dict: Dictionary containing season stats for the given position.

    """
    qual_pass_att = 14.0 * (16 if season < 2021 else 17)
    qual_rush_att = 6.25 * (16 if season < 2021 else 17)
    qual_rec = 1.875 * (16 if season < 2021 else 17)
    qual_fga = 1.0 * (16 if season < 2021 else 17)

    season_stats_dict = {}
    for raw_player_id, player_stats in raw_season_stats.items():
        player_id = str(raw_player_id)
        player = position_players.get(player_id)
        if player is None:
            continue

        if (
            ("pass_att" in player_stats and player_stats["pass_att"] >= qual_pass_att)
            or ("rush_att" in player_stats and player_stats["rush_att"] >= qual_rush_att)
            or ("rec" in player_stats and player_stats["rec"] >= qual_rec)
            or ("fga" in player_stats and player_stats["fga"] >= qual_fga)
            or position == "DEF"
        ):
            player_stats_with_adp = dict(player_stats)
            player_stats_with_adp.update(get_player_adp_ranks(raw_season_projections, player_id))
            season_stats_dict[player_id] = {
                "name": player["name"],
                "position": position,
                "team": player["team"],
                "stats": player_stats_with_adp,
            }
    return season_stats_dict


def get_position_stats(season_stats_dict: dict) -> list[str]:
    """Get a sorted list of position stats from the season stats dictionary.

    Args:
        season_stats_dict: Dictionary containing season stats.

    Returns:
        list[str]: List of position stats.

    """
    position_stats_list = []
    for player in season_stats_dict.values():
        if "stats" in player:
            for stat_name in player["stats"]:
                if stat_name not in position_stats_list:
                    position_stats_list.append(stat_name)
    position_stats_list.sort()
    return position_stats_list


def create_season_player_list(
    season: int, season_stats_dict: dict, position_stats_list: list[str]
) -> list[dict[str, str | float | int | None]]:
    """Create a list of player stats for the season.

    Args:
        season: The season year.
        season_stats_dict: Dictionary containing season stats.
        position_stats_list: List of position stats.

    Returns:
        list[dict[str, str | float | int | None]]: List of player stats for the season.

    """
    player_list = []
    for player_id, player in season_stats_dict.items():
        player_dict: dict[str, str | float | int | None] = {
            "player_id": player_id,
            "name": player["name"],
            "position": player["position"],
            "team": player["team"],
            "season": season,
        }
        if "stats" in player:
            for stat_name in position_stats_list:
                stat_value = player["stats"].get(stat_name, 0.0)
                player_dict[stat_name] = 0.0 if stat_value is None else float(stat_value)
        player_list.append(player_dict)
    return player_list


def get_week_stats(
    position_players: PositionPlayerIndex,
    raw_week_stats: dict,
    season: int,
    week: int,
    position: str,
) -> pl.DataFrame:
    """Get week stats for a given position and return them as a DataFrame.

    Args:
        position_players: Player metadata indexed by player ID for the requested position.
        raw_week_stats: Dictionary containing raw week stats.
        season: The season year.
        week: The week number.
        position: The position to filter stats by.

    Returns:
        pl.DataFrame: DataFrame containing week stats for the given position.

    """
    week_stats_dict = create_week_stats_dict(position_players, raw_week_stats, position)
    position_stats_list = get_position_stats(week_stats_dict)
    week_player_stats_list = create_week_player_list(
        season, week, week_stats_dict, position_stats_list
    )
    return pl.DataFrame(week_player_stats_list) if week_player_stats_list else pl.DataFrame()


def create_week_stats_dict(
    position_players: PositionPlayerIndex,
    raw_week_stats: dict,
    position: str,
) -> dict:
    """Create a dictionary of week stats for a given position.

    Args:
        position_players: Player metadata indexed by player ID for the requested position.
        raw_week_stats: Dictionary containing raw week stats.
        position: The position to filter stats by.

    Returns:
        dict: Dictionary containing week stats for the given position.

    """
    week_stats_dict = {}
    for raw_player_id, player_stats in raw_week_stats.items():
        player_id = str(raw_player_id)
        player = position_players.get(player_id)
        if player is not None:
            week_stats_dict[player_id] = {
                "name": player["name"],
                "position": position,
                "team": player["team"],
                "stats": player_stats,
            }
    return week_stats_dict


def create_week_player_list(
    season: int,
    week: int,
    season_stats_dict: dict,
    position_stats_list: list[str],
) -> list[dict[str, str | float | int | None]]:
    """Create a list of player stats for the week.

    Args:
        season: The season year.
        week: The week number.
        season_stats_dict: Dictionary containing season stats.
        position_stats_list: List of position stats.

    Returns:
        list[dict[str, str | float | int | None]]: List of player stats for the week.

    """
    player_list = []
    for player_id, player in season_stats_dict.items():
        player_dict: dict[str, str | float | int | None] = {
            "player_id": player_id,
            "name": player["name"],
            "position": player["position"],
            "team": player["team"],
            "season": season,
            "week": week,
        }
        if "stats" in player:
            for stat_name in position_stats_list:
                player_dict[stat_name] = float(player["stats"].get(stat_name, 0.0) or 0.0)
        player_list.append(player_dict)
    return player_list


def combine_position_stats(
    position: str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> pl.DataFrame:
    """Combine the statistics of a specific position from multiple seasons into a single DataFrame.

    Args:
        position: The position for which the statistics are to be combined.
        start_year: First season year to include.
        end_year: Exclusive upper bound for season years to include.

    Returns:
        pl.DataFrame: Combined statistics for the specified position.

    """
    resolved_start_year = START_YEAR if start_year is None else start_year
    resolved_end_year = END_YEAR if end_year is None else end_year

    season_frames: list[pl.DataFrame] = []
    for season in range(resolved_start_year, resolved_end_year):
        file_path = f"{constants.DATA_PATH}/{season}_{position}_stats.csv"
        season_frames.append(read_df_from_csv(file_path))

    if not season_frames:
        return pl.DataFrame()

    combined_stats = pl.concat(season_frames, how="diagonal_relaxed")

    all_stats = constants.USED_STATS["ALL"]
    cols_to_keep = [col for col in all_stats if col in combined_stats.columns]
    if not cols_to_keep:
        return pl.DataFrame()

    combined_stats = combined_stats.select(cols_to_keep)
    combined_stats = combined_stats.with_columns(cs.numeric().fill_null(0))
    return combined_stats.with_columns(cs.float().fill_nan(0))


if __name__ == "__main__":
    main()
