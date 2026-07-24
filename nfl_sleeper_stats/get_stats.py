"""
This module provides functions to retrieve and process NFL player statistics. It includes functions
to get all players, season stats, and week stats, and save them to CSV files. The main function
orchestrates the retrieval and saving of these statistics.

Functions:
    main(): Main function to get stats for all players and save them to CSV files.
    get_all_players(): Get all players and return as a DataFrame.
    get_season_stats(all_players_df, raw_season_stats, season, position): Get season stats for a
        given position and return as a DataFrame.
    create_season_stats_dict(all_players_df, raw_season_stats, position): Create a dictionary of
        season stats for a given position.
    get_position_stats(season_stats_dict): Get a list of position stats from the season stats
        dictionary.
    create_season_player_list(season, season_stats_dict, position_stats_list): Create a list of
        player stats for the season.
    get_week_stats(all_players_df, raw_week_stats, season, week, position): Get week stats for a
        given position and return as a DataFrame.
    create_week_stats_dict(all_players_df, raw_week_stats, position): Create a dictionary of week
        stats for a given position.
    create_week_player_list(season, week, season_stats_dict, position_stats_list): Create a list of
        player stats for the week.
"""

import pandas as pd
from sleeper_wrapper import Players, Stats

from nfl_stats import constants
from nfl_stats.utils.csv_utils import read_df_from_csv, read_write_data
from nfl_stats.utils.logger import log

START_YEAR = 2009
END_YEAR = 2025
SEASON_TYPE = "regular"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
PLAYER_COLUMNS = ["player_id", "name", "position", "team"]
TEAM_ABBR_MAP = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}


def main() -> None:
    """
    Main function to get stats for all players and save them to CSV files.
    """
    all_players_df = read_write_data("all_players", get_all_players)
    stats = Stats()
    for season in range(START_YEAR, END_YEAR):
        raw_season_stats = stats.get_all_stats(SEASON_TYPE, season)
        raw_season_stats = remap_team_abbr_in_stats(raw_season_stats)
        for position in POSITIONS:
            season_stats_name = f"{season}_{position}_stats"
            season_stats_df = read_write_data(
                season_stats_name,
                get_season_stats,
                all_players_df,
                raw_season_stats,
                season,
                position,
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
        #         all_players_df,
        #         raw_week_stats,
        #         season,
        #         week,
        #         "DEF",
        #     )
        #     log.debug("%s - Week %s - DEF:\n%s", season, week, week_stats_df)

    for position in POSITIONS:
        read_write_data(f"{position}_stats", combine_position_stats, position)


def get_all_players() -> pd.DataFrame:
    """
    Get all players and return as a DataFrame.

    Returns:
        pd.DataFrame:   DataFrame containing all players with columns ['player_id', 'name',
                        'position', 'team'].
    """
    players = Players()
    all_players = players.get_all_players()
    players_list = []
    for player in all_players.values():
        player_position = player.get("position")
        if player_position in POSITIONS:
            player_id = player.get("player_id")
            if "full_name" in player:
                player_name = player.get("full_name")
            else:
                first_name = player.get("first_name")
                last_name = player.get("last_name")
                player_name = f"{first_name} {last_name}"
            player_team = player.get("team")
            player_list = [player_id, player_name, player_position, player_team]
            players_list.append(player_list)
    all_players_df = pd.DataFrame(players_list, columns=PLAYER_COLUMNS)
    all_players_df["player_id"] = all_players_df["player_id"].astype(str)
    all_players_df["player_id"] = all_players_df["player_id"].apply(
        lambda x: int(x) if str(x).isdigit() else x
    )
    all_players_df = all_players_df.sort_values(
        by=["player_id"], key=lambda x: x.apply(lambda y: (isinstance(y, int), y))
    )
    all_players_df = all_players_df.reset_index(drop=True)
    return all_players_df


def remap_team_abbr_in_stats(stats_dict):
    """
    Remap team abbreviations in the stats dictionary.

    Args:
        stats_dict (dict): Dictionary containing player statistics with team abbreviations.
    """
    for player_id in list(stats_dict.keys()):
        if player_id in TEAM_ABBR_MAP:
            new_id = TEAM_ABBR_MAP[player_id]
            stats_dict[new_id] = stats_dict[player_id]
            del stats_dict[player_id]
    return stats_dict


def get_season_stats(
    all_players_df: pd.DataFrame, raw_season_stats: dict, season: int, position: str
) -> pd.DataFrame:
    """
    Get season stats for a given position and return as a DataFrame.

    Args:
        all_players_df (pd.DataFrame): DataFrame containing all players.
        raw_season_stats (dict): Dictionary containing raw season stats.
        season (int): The season year.
        position (str): The position to filter stats by.

    Returns:
        pd.DataFrame: DataFrame containing season stats for the given position.
    """
    season_stats_dict = create_season_stats_dict(all_players_df, raw_season_stats, season, position)
    position_stats_list = get_position_stats(season_stats_dict)
    season_player_stats_list = create_season_player_list(
        season, season_stats_dict, position_stats_list
    )
    season_player_stats_df = pd.DataFrame(season_player_stats_list)
    season_player_stats_df = season_player_stats_df.sort_values("rank_std", ascending=True)
    season_player_stats_df = season_player_stats_df.reset_index(drop=True)
    return season_player_stats_df


def create_season_stats_dict(
    all_players_df: pd.DataFrame, raw_season_stats: dict, season: int, position: str
) -> dict:
    """
    Create a dictionary of season stats for a given position.

    Args:
        all_players_df (pd.DataFrame): DataFrame containing all players.
        raw_season_stats (dict): Dictionary containing raw season stats.
        position (str): The position to filter stats by.

    Returns:
        dict: Dictionary containing season stats for the given position.
    """
    qual_pass_att = 14.0 * (16 if season < 2021 else 17)
    qual_rush_att = 6.25 * (16 if season < 2021 else 17)
    qual_rec = 1.875 * (16 if season < 2021 else 17)
    qual_fga = 1.0 * (16 if season < 2021 else 17)

    # Filter players by position
    filtered_players_df = all_players_df[all_players_df["position"] == position]

    season_stats_dict = {}
    for player_id, player_stats in raw_season_stats.items():
        player_id_mask = filtered_players_df["player_id"].astype(str) == str(player_id)
        if player_id_mask.any():
            filtered = filtered_players_df.loc[player_id_mask]
            if not filtered.empty:
                if (
                    ("pass_att" in player_stats and player_stats["pass_att"] >= qual_pass_att)
                    or ("rush_att" in player_stats and player_stats["rush_att"] >= qual_rush_att)
                    or ("rec" in player_stats and player_stats["rec"] >= qual_rec)
                    or ("fga" in player_stats and player_stats["fga"] >= qual_fga)
                    or position == "DEF"
                ):
                    player_position = filtered["position"].iloc[0]
                    if player_position == position:
                        player_name = filtered["name"].iloc[0]
                        player_team = filtered["team"].iloc[0]
                        season_stats_dict[player_id] = {}
                        season_stats_dict[player_id]["name"] = player_name
                        season_stats_dict[player_id]["position"] = player_position
                        season_stats_dict[player_id]["team"] = player_team
                        season_stats_dict[player_id]["stats"] = player_stats
    return season_stats_dict


def get_position_stats(season_stats_dict: dict) -> list:
    """
    Get a list of position stats from the season stats dictionary.

    Args:
        season_stats_dict (dict): Dictionary containing season stats.

    Returns:
        list: List of position stats.
    """
    position_stats_list = []
    for player in season_stats_dict.values():
        if "stats" in player:
            for stat_name in player["stats"].keys():
                if stat_name not in position_stats_list:
                    position_stats_list.append(stat_name)
    position_stats_list.sort()
    return position_stats_list


def create_season_player_list(
    season: int, season_stats_dict: dict, position_stats_list: list
) -> list:
    """
    Create a list of player stats for the season.

    Args:
        season (int): The season year.
        season_stats_dict (dict): Dictionary containing season stats.
        position_stats_list (list): List of position stats.

    Returns:
        list: List of player stats for the season.
    """
    player_list = []
    for player_id, player in season_stats_dict.items():
        player_dict = {}
        player_dict["player_id"] = player_id
        player_dict["name"] = player["name"]
        player_dict["position"] = player["position"]
        player_dict["team"] = player["team"]
        player_dict["season"] = season
        if "stats" in player:
            for stat_name in position_stats_list:
                stat_value = player["stats"].get(stat_name, 0.0)
                if stat_value is None:
                    player_dict[stat_name] = 0.0
                else:
                    player_dict[stat_name] = float(stat_value)
        player_list.append(player_dict)
    return player_list


def get_week_stats(
    all_players_df: pd.DataFrame, raw_week_stats: dict, season: int, week: int, position: str
) -> pd.DataFrame:
    """
    Get week stats for a given position and return as a DataFrame.

    Args:
        all_players_df (pd.DataFrame): DataFrame containing all players.
        raw_week_stats (dict): Dictionary containing raw week stats.
        season (int): The season year.
        week (int): The week number.
        position (str): The position to filter stats by.

    Returns:
        pd.DataFrame: DataFrame containing week stats for the given position.
    """
    week_stats_dict = create_week_stats_dict(all_players_df, raw_week_stats, position)
    position_stats_list = get_position_stats(week_stats_dict)
    week_player_stats_list = create_week_player_list(
        season, week, week_stats_dict, position_stats_list
    )
    week_player_stats_df = pd.DataFrame(week_player_stats_list)
    week_player_stats_df["player_id"] = week_player_stats_df["player_id"]
    week_player_stats_df = week_player_stats_df.set_index("player_id", drop=False)
    return week_player_stats_df


def create_week_stats_dict(
    all_players_df: pd.DataFrame, raw_week_stats: dict, position: str
) -> dict:
    """
    Create a dictionary of week stats for a given position.

    Args:
        all_players_df (pd.DataFrame): DataFrame containing all players.
        raw_week_stats (dict): Dictionary containing raw week stats.
        position (str): The position to filter stats by.

    Returns:
        dict: Dictionary containing week stats for the given position.
    """
    week_stats_dict = {}
    for player_id, player_stats in raw_week_stats.items():
        player_id_mask = all_players_df["player_id"].astype(str) == str(player_id)
        if player_id_mask.any():
            filtered = all_players_df.loc[player_id_mask]
            if not filtered.empty:
                player_position = filtered["position"].iloc[0]
                if player_position == position:
                    player_name = filtered["name"].iloc[0]
                    player_team = filtered["team"].iloc[0]
                    week_stats_dict[player_id] = {}
                    week_stats_dict[player_id]["name"] = player_name
                    week_stats_dict[player_id]["position"] = player_position
                    week_stats_dict[player_id]["team"] = player_team
                    week_stats_dict[player_id]["stats"] = player_stats
    return week_stats_dict


def create_week_player_list(
    season: int, week: int, season_stats_dict: dict, position_stats_list: list
) -> list:
    """
    Create a list of player stats for the week.

    Args:
        season (int): The season year.
        week (int): The week number.
        season_stats_dict (dict): Dictionary containing season stats.
        position_stats_list (list): List of position stats.

    Returns:
        list: List of player stats for the week.
    """
    player_list = []
    for player_id, player in season_stats_dict.items():
        player_dict = {}
        player_dict["player_id"] = player_id
        player_dict["name"] = player["name"]
        player_dict["position"] = player["position"]
        player_dict["team"] = player["team"]
        player_dict["season"] = season
        player_dict["week"] = week
        if "stats" in player:
            for stat_name in position_stats_list:
                if stat_name in player["stats"]:
                    player_dict[stat_name] = float(player["stats"][stat_name])
                else:
                    player_dict[stat_name] = float(0.0)
        player_list.append(player_dict)
    return player_list


def combine_position_stats(position: str) -> pd.DataFrame:
    """
    Combine the statistics of a specific position from multiple seasons into a single DataFrame.

    Args:
        position (str): The position for which the statistics are to be combined.

    Returns:
        pd.DataFrame: A DataFrame containing the combined statistics of the specified position.
    """
    combined_stats = pd.DataFrame()
    for season in range(START_YEAR, END_YEAR):
        file_path = f"{constants.DATA_PATH}/{season}_{position}_stats.csv"
        season_stats = read_df_from_csv(file_path)
        combined_stats = pd.concat([combined_stats, season_stats])

    # Use the ALL stats for columns, but only keep those present in the DataFrame
    all_stats = constants.POSITION_STATS["ALL"]
    # Only keep columns that exist in the DataFrame
    cols_to_keep = [col for col in all_stats if col in combined_stats.columns]
    combined_stats = combined_stats[cols_to_keep]

    # Fill NaN for all columns except 'team'
    combined_stats = combined_stats.apply(lambda col: col if col.name == "team" else col.fillna(0))
    return combined_stats


if __name__ == "__main__":
    main()
