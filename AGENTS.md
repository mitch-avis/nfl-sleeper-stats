# AGENTS.md

Guidance for AI coding agents working on `nfl-sleeper-stats`. Treat `pyproject.toml` and the source
tree as the ground truth when documentation disagrees.

## Project overview

`nfl-sleeper-stats` pulls NFL player and team-defense stats from the Sleeper API, writes
season-by-position CSVs under `data/`, and builds combined historical position files such as
`QB_stats.csv` and `DEF_stats.csv`.

The current generated outputs are centered on:

- `all_players.csv`
- season files like `2024_QB_stats.csv`
- combined position files like `QB_stats.csv`
- the raw Sleeper stat-field catalog in `nfl_sleeper_stats/constants.py`

## Stack

- Python 3.14+ (`requires-python = ">=3.14"`)
- `polars` for dataframe work
- `sleeper-api-wrapper` for `Players` and `Stats`
- stdlib `logging` plus `coloredlogs` formatting
- `uv` plus `uv.lock` for environment and dependency management

## Environment and commands

Set up the project environment from the repo root:

```bash
uv venv .venv
source .venv/bin/activate
uv sync --active
```

When you change Python code, use these as the default validation commands:

```bash
ruff format .
ruff check .
ty check .
pyright .
pytest
```

Notes:

- `pytest` is configured in `pyproject.toml`, and `tests/` now covers the core transform and CSV
  cache paths.
- If you add or change logic, extend the focused tests under `tests/` rather than relying on manual
  checks.
- When you touch repo-owned Markdown, run `markdownlint` on the files you changed.

Run the current data puller with:

```bash
python -m nfl_sleeper_stats.get_stats
```

Or pass explicit year bounds and cache behavior:

```bash
nfl-sleeper-stats --start-year 2018 --end-year 2025 --force-refresh
```

The console script entry in `pyproject.toml` currently points at `nfl_sleeper_stats.get_stats:main`.

## Dependency workflow

- Edit `pyproject.toml` for dependency changes.
- Run `./update_requirements.sh` from an active project `.venv`.
- The script updates `uv.lock`, syncs the active environment, and refreshes compatibility
  `requirements*.txt` exports only if those files exist.
- Do not hand-edit `uv.lock`.

## Repository layout

The codebase is relatively small. Read the module you are changing rather than assuming a larger
pipeline exists.

- `nfl_sleeper_stats/get_stats.py` orchestrates the data pull, season file generation, and position
  aggregation.
- `nfl_sleeper_stats/constants.py` defines data-path resolution and curated stat column lists.
- `nfl_sleeper_stats/utils/csv_utils.py` contains Polars-based CSV caching and read/write helpers.
- `nfl_sleeper_stats/utils/logger.py` configures logging.
- `data/` holds generated CSV artifacts and should not be treated as source code.
- `tests/` contains the automated regression suite.

## Domain rules that are easy to get wrong

These are the current project-specific invariants visible in source. Linters will not catch
violations.

- **Regular season only.** The current loader uses `SEASON_TYPE = "regular"`.
- **Supported positions are fixed.** The current workflow only includes `QB`, `RB`, `WR`, `TE`, `K`,
  and `DEF`.
- **The CLI end year is exclusive.** `run()` defaults to seasons 2009 through the prior completed
  season by using the current year as the exclusive upper bound.
- **Normalize legacy team abbreviations before downstream use.** `remap_team_abbr_in_stats()`
  currently remaps `OAK -> LV`, `SD -> LAC`, and `STL -> LAR`. Preserve or intentionally extend that
  mapping when changing joins or filters.
- **Match player IDs by string form.** The code normalizes `player_id` values to strings and
  compares them as strings to handle mixed Sleeper identifiers.
- **Player metadata is indexed once per run.** `build_player_index()` creates a position-scoped
  lookup that season and week transforms reuse rather than filtering the player frame repeatedly.
- **Season qualification thresholds depend on season length.** The filters for pass attempts, rush
  attempts, receptions, and field-goal attempts use 16-game thresholds before 2021 and 17-game
  thresholds from 2021 onward.
- **`DEF` intentionally bypasses those qualification thresholds.** Do not apply the same filters to
  defensive team rows unless the task explicitly changes the published behavior.
- **CSV files are the cache boundary.** `read_write_data()` prefers existing files unless
  `force_refresh=True`. If you need a fresh pull, thread refresh behavior through the code rather
  than telling people to delete generated data by hand.
- **The default cache location is repo-local.** Runs launched from the repository write into `data/`
  under the repo root unless `NFL_SLEEPER_STATS_DATA_DIR` is set explicitly.
- **Combined position files depend on the selected season window.** `run()` always rebuilds those
  derived CSVs even when season-level cache files are reused.
- **`ALL_STATS` must cover the raw Sleeper payload fields.** Refresh it from a saved season payload
  such as `2025_all_stats.json`, and keep historically relevant fields when they still matter.
- **Combined position outputs are schema-curated.** `combine_position_stats()` keeps only columns
  present in the frame and orders them from `constants.USED_STATS["ALL"]`. If you add or rename
  published columns, update that registry deliberately.
- **Weekly support is partial.** The week-level helpers exist, but the loop that writes weekly CSVs
  is commented out in `main()`. If you re-enable it, preserve the existing pre-2021 week-18
  exclusion.

## Code conventions

- Prefer minimal changes inside the current Polars-based architecture.
- Keep changes inside the current Sleeper and Polars-based workflow unless the task explicitly asks
  for a broader redesign.
- Keep public modules and functions docstring-complete and Ruff-compliant.
- Reuse `csv_utils` for cached CSV generation and `logger.log` for diagnostics instead of
  duplicating file I/O or logging patterns.
- Preserve the current CSV index behavior unless a task explicitly migrates the stored file format.
- When adding non-trivial logic, add focused pytest coverage under `tests/` first.

## Boundaries

- Always run the relevant format, lint, type-check, and test commands for the scope you changed.
- Always run `markdownlint` on repo-owned Markdown files you edited.
- Ask first before changing the supported position list, season range, data source, generated CSV
  filenames, or qualification rules.
- Never hand-edit generated CSVs under `data/` as if they were source files.
- Never use system Python for repo work; use the project `.venv`.
- Never weaken Ruff, Ty, Pyright, or pytest configuration to make a task pass.

## Known repo edges

- Weekly support is still partial even though the helper functions exist.
- Preserve the historical CSV cache shape unless a task explicitly migrates stored files.
