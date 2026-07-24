"""Read and write cached CSV data for nfl_sleeper_stats.

These helpers manage the CSV cache boundary used by the stats puller.
"""

import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import polars as pl

from nfl_sleeper_stats.constants import DATA_PATH
from nfl_sleeper_stats.utils.logger import log


def _as_dataframe(data: pl.DataFrame | Sequence[Mapping[str, object]]) -> pl.DataFrame:
    """Convert supported tabular data into a Polars DataFrame."""
    if isinstance(data, pl.DataFrame):
        return data
    return pl.DataFrame(data)


def read_write_data(
    data_name: str,
    func: Callable[..., pl.DataFrame | Sequence[Mapping[str, object]]],
    *args,
    force_refresh: bool = False,
    **kwargs,
) -> pl.DataFrame:
    """Read cached data or generate it and persist it to CSV.

    This function checks if a CSV file with the given data name exists. If it does and
    force_refresh is False, it reads the data from the file. Otherwise, it generates the data by
    calling the provided function and writes the new data to a CSV file.

    Args:
        data_name (str): The base name of the data file (without extension).
        func (Callable[..., pl.DataFrame | Sequence[Mapping[str, object]]]): The function to
            generate data if needed.
        *args: Positional arguments to pass to the data generation function.
        force_refresh (bool, optional): If True, forces data regeneration. Defaults to False.
        **kwargs: Keyword arguments to pass to the data generation function.

    Returns:
        pl.DataFrame: The data as a Polars DataFrame.

    """
    dataframe = pl.DataFrame()
    file_path = Path(DATA_PATH) / f"{data_name}.csv"

    if file_path.is_file() and not force_refresh:
        dataframe = read_df_from_csv(file_path, check_exists=False)

    if dataframe.is_empty() or force_refresh:
        func_name = getattr(func, "__name__", func.__class__.__name__)
        log.debug("* Calling %s()", func_name)
        dataframe = _as_dataframe(func(*args, **kwargs))
        write_df_to_csv(dataframe, file_path)

    return dataframe


def read_df_from_csv(file_path: str | Path, check_exists: bool = True) -> pl.DataFrame:
    """Read a DataFrame from a CSV file.

    If check_exists is True, the function first checks if the file exists. If it does not, logs an
    error message and exits the program.

    Args:
        file_path (str | Path): The path to the CSV file.
        check_exists (bool, optional): Whether to check if the file exists before reading.

    Returns:
        pl.DataFrame: The data read from the CSV file.

    """
    path = Path(file_path)
    if check_exists and not path.is_file():
        log.error("%s not found!", path.name)
        sys.exit(1)

    dataframe = pl.read_csv(path)
    # Cached files keep a leading blank index column for compatibility with older generated CSVs.
    if "" in dataframe.columns:
        dataframe = dataframe.drop("")
    if "player_id" in dataframe.columns:
        dataframe = dataframe.with_columns(pl.col("player_id").cast(pl.String))
    return dataframe


def write_df_to_csv(dataframe: pl.DataFrame, file_path: str | Path) -> None:
    """Write a DataFrame to a CSV file.

    If the directory for the file does not exist, it is created. The DataFrame is then written to
    the file, including the index.

    Args:
        dataframe (pl.DataFrame): The DataFrame to write.
        file_path (str | Path): The path to the CSV file where the data should be written.

    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the historical pandas-style blank index column so existing cache files stay readable.
    dataframe.with_row_index(name="").write_csv(path, quote_style="never")
    log.debug("Data written to %s", path.name)
