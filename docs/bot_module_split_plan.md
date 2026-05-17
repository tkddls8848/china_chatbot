# bot.py Module Split Plan

## Current State

`app/bot.py` is still the application composition file and contains several feature areas that can be split further. As of this plan:

- Research modules have been moved under `app/research/`.
- Raw Akshare source fetchers have been split into `app/news_sources.py`.
- `app/bot.py` still contains news delivery, research-news collection, watchlist state, watchlist handlers, message formatting, and configuration constants.

Current important files:

```text
app/
  bot.py
  news_sources.py
  research/
    __init__.py
    handlers.py
    candidates.py
    market_view.py
  stock_db.py
  translator.py
```

## Split Goals

- Keep `bot.py` as an app assembly entrypoint only.
- Make each feature folder understandable without reading the whole bot.
- Reduce LLM context cost during future edits.
- Avoid large cross-module imports and string-key coupling where practical.
- Move in small stages and verify with `py_compile` and `import bot` after each stage.

## Target Structure

```text
app/
  bot.py
  config.py

  news/
    __init__.py
    sources.py
    delivery.py
    formatting.py

  research/
    __init__.py
    handlers.py
    candidates.py
    market_view.py
    news.py

  watchlist/
    __init__.py
    manager.py
    handlers.py
    keyboards.py

  state/
    __init__.py
    sent_tracker.py
```

## Stage 1: News Package

Status: partially done.

Already split:

- `app/news_sources.py`
  - `retry_on_network`
  - `fetch_cls_raw`
  - `fetch_futu_raw`
  - `fetch_stock_news_raw`

Recommended next shape:

```text
app/news/
  __init__.py
  sources.py
  delivery.py
  formatting.py
```

Move targets from `bot.py`:

- `fetch_cls`
- `fetch_futu`
- `fetch_stock_news`
- `_format_china_time_as_kst`
- `_build_news_message`
- `_translate_article`

Notes:

- `sources.py` should contain only Akshare raw API fetches and retry policy.
- `delivery.py` should contain Telegram send workflows.
- `formatting.py` should contain Telegram message formatting helpers.
- `bot.py` should call one orchestration function or keep a small `fetch_all` wrapper.

## Stage 2: Research News Collection

Recommended file:

```text
app/research/news.py
```

Move targets from `bot.py`:

- `collect_watchlist_news_items`
- `collect_global_market_news_items`
- `_make_news_item`
- `_row_value`

Why:

- These functions are used as input preparation for `/research run`.
- Keeping them in `bot.py` forces `research.handlers` to depend on `bot_data["research_news_collector"]`.
- Moving them to `research/news.py` lets `research.handlers` import the collector directly or receive a typed dependency more clearly.

Expected cleanup:

- Remove `app.bot_data["research_news_collector"]`.
- Replace string-key lookup in `research/handlers.py` with direct import or an explicit dependency object.

## Stage 3: Watchlist Package

Recommended files:

```text
app/watchlist/
  __init__.py
  manager.py
  handlers.py
  keyboards.py
```

Move targets from `bot.py`:

- `WatchlistManager`
- `build_list_keyboard`
- `cmd_menu`
- `cmd_add`
- `cmd_list`
- remove callback branch in `callback_handler`
- `_resolve_stock_name`

Notes:

- `_resolve_stock_name` uses Akshare but is watchlist-specific because it resolves manually-added stock codes.
- `callback_handler` in `bot.py` should become a small dispatcher, or watchlist callbacks can expose `handle_watchlist_callback`.

## Stage 4: State Package

Recommended file:

```text
app/state/sent_tracker.py
```

Move targets from `bot.py`:

- `SentNewsTracker`

Why:

- This class is unrelated to Telegram handlers and news parsing.
- It is shared state for duplicate-send prevention.

## Stage 5: Config Module

Recommended file:

```text
app/config.py
```

Move targets from `bot.py`:

- `BASE_DIR`
- `BOT_TOKEN`
- `CHAT_ID`
- all data file paths
- prompt paths
- message/news/research/scheduler limits
- `DEFAULT_WATCHLIST`
- `HELP_TEXT`

Notes:

- Do config extraction late because many modules currently import constants implicitly through `bot.py`.

## Final bot.py Shape

After all stages, `bot.py` should contain mainly:

- logging setup
- `main()`
- dependency construction
- handler registration
- scheduler registration
- a small top-level callback dispatcher if needed

Expected rough size target:

- `bot.py`: 150-250 lines
- feature modules: 100-450 lines each

## Verification Checklist Per Stage

Run after every stage:

```powershell
.\venv\Scripts\python.exe -B -m py_compile app\bot.py app\translator.py app\stock_db.py
.\venv\Scripts\python.exe -B -c "import sys; sys.path.insert(0, 'app'); import bot; print('import ok')"
```

Also run package-specific compile checks for newly moved files.

## Current Caution

The repository has unrelated working-tree changes outside this plan. Do not revert them unless explicitly requested.
