# nfl-sleeper-stats

Pull regular-season NFL player stats from the Sleeper API and write them to CSV files for local use
and analysis.

The current implementation uses Polars for in-memory transforms and preserves the historical CSV
cache format so existing files remain compatible.

## Overview

The current pipeline:

1. Downloads the Sleeper player directory and writes `data/all_players.csv`.
2. Fetches regular-season stats and season projections for each season in the requested CLI window.
3. Writes season-by-position files for `QB`, `RB`, `WR`, `TE`, `K`, and `DEF`.
4. Rebuilds combined position files such as `data/QB_stats.csv` and `data/DEF_stats.csv` from the
  requested season range.

Example outputs:

- `data/all_players.csv`
- `data/2024_QB_stats.csv`
- `data/2024_DEF_stats.csv`
- `data/QB_stats.csv`
- `data/DEF_stats.csv`

## Requirements

- Python 3.14+
- `uv` for environment and dependency management

## Setup

From the repository root:

```bash
uv venv .venv
source .venv/bin/activate
uv sync --active
```

## Run

After syncing the environment, run either of these entrypoints:

```bash
python -m nfl_sleeper_stats.get_stats
```

```bash
nfl-sleeper-stats
```

The default CLI window is `--start-year 2009 --end-year <current year>`. `--end-year` is an
exclusive upper bound, so the default current-year value includes seasons through last year. Season
CSVs reuse the existing cache unless `--force-refresh` is supplied. Combined position CSVs are
always rebuilt from the selected season window so custom ranges stay correct.

Example:

```bash
nfl-sleeper-stats --start-year 2018 --end-year 2025 --force-refresh
```

## Output location

By default, runs launched from the repository write into `data/` under the repo root. Set
`NFL_SLEEPER_STATS_DATA_DIR` to override the output directory explicitly.

The CSV helpers keep the legacy leading blank index column in written files so older cached outputs
remain readable after the Polars migration.

`nfl_sleeper_stats/constants.py` also tracks the raw Sleeper stat catalog in `ALL_STATS`. That list
covers the fields present in the saved `2025_all_stats.json` snapshot and may also retain
historically relevant Sleeper fields that are absent from that single season.

## Current behavior

- Only regular-season stats are fetched.
- Legacy team abbreviations are normalized before downstream use: `OAK -> LV`, `SD -> LAC`, `STL ->
  LAR`.
- Player IDs are compared as strings so mixed Sleeper identifier formats continue to match.
- Player metadata is indexed once per run, then reused across every season and position lookup.
- Selected ADP ranks from the projections endpoint are attached when available: `adp_2qb`,
  `adp_dynasty`, `adp_dynasty_2qb`, `adp_dynasty_half_ppr`, `adp_dynasty_ppr`, `adp_half_ppr`,
  and `adp_ppr`.
- Season qualification thresholds differ for pre-2021 and 2021+ seasons to reflect 16-game versus
  17-game schedules.
- Defensive rows are included without the player volume thresholds used for other positions.
- Week-level helper functions exist, but the default run currently writes season-level and combined
  position CSVs.

## Development

Run the standard checks from the repo root:

```bash
ruff format .
ruff check .
ty check .
pyright .
pytest
```

The current suite covers the core pipeline, CSV cache compatibility, and aggregation path at about
90% package coverage. Add focused tests under `tests/` when changing logic.

For dependency changes, edit `pyproject.toml` and then run:

```bash
./update_requirements.sh
```

The script expects the project `.venv` to exist and be activated before you run it.

## Project layout

- `nfl_sleeper_stats/get_stats.py` orchestrates the data pull and CSV generation.
- `nfl_sleeper_stats/constants.py` defines data-path resolution, the raw Sleeper stat catalog, and
  curated output columns.
- `nfl_sleeper_stats/utils/csv_utils.py` handles cached CSV reads and writes with Polars.
- `nfl_sleeper_stats/utils/logger.py` configures logging.
- `data/` stores generated CSV artifacts.
- `tests/` contains the automated regression suite.
