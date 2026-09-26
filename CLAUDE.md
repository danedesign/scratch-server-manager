# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

All 9 build-order milestones are done: the core engine, both profiles, staging/promote, the SQLite-aware integrity check, config loading, the Flask status dashboard with folder picker and manual controls, and now persistent logging + pluggable failure alerting. That's the full v1 scope from the original planning notes — there is no Milestone 10. Genuine open items that came up along the way (not gaps in the build order, just natural next steps) are noted inline where they're relevant: no `engine/scheduler.py` yet (see WeChat Vault, below), no Syncthing status integration for Hot Data (see Hot Data, below), and editing settings on an already-running Hot Data folder needs a restart (see Config format, below). Update this file as any of those get built.

**Deviation from the original planning notes**: the config schema's example showed a single `path` key for every folder, but a `wechat_vault` entry needs `staging_path` + `vault_path` explicitly (see Config format below) — staging and vault are independent locations that could reasonably sit on different disks, so deriving one from the other the way Hot Data derives its sibling `.versions` dir would be guessing at a layout, not inferring it.

## What this project is

A single local app, targeting Debian, that manages two categories of folder sync, each with different safety rules, through one shared engine instead of two separate tools:

- **Hot Data** — everyday working files that should sync quickly across devices; low corruption risk, no staging delay.
- **WeChat Vault** — a single WeChat data folder shared across machines (only one machine is ever logged into WeChat at a time). Writes must be staged and integrity-checked before being promoted to the live vault, to avoid corrupting the SQLite-backed chat history if a machine or connection drops mid-write.

Samba already serves the underlying shares on the target Debian host — this app manages what happens to files *within* those shares; it does not replace the network transport.

## Architecture: one engine, two profiles

The user assigns a folder to a category ("profile") via the web UI; the profile determines sync behavior, but both profiles run through the same engine, so improvements to staging/integrity logic in `engine/` benefit both:

```
sync-manager/
├── engine/
│   ├── watcher.py        # detects file changes in managed folders
│   ├── checksum.py       # hashing / change detection
│   ├── staging.py        # staging-copy + atomic promote logic
│   ├── integrity.py      # pluggable integrity checks per profile
│   ├── config.py         # folders.yaml parsing + per-profile validation
│   ├── alerting.py       # pluggable failure notification (ntfy/webhook-style POST)
│   ├── scheduler.py      # not yet built - interval-based promotion for staged profiles
│   └── logger.py         # structured logs to stdout + logs/sync-manager.log
├── profiles/
│   ├── hot_data.py       # continuous sync, basic checksum verification
│   └── wechat_vault.py   # staged sync, SQLite integrity check, single-writer aware
├── config/
│   └── folders.yaml      # user-assigned folder → profile mapping
├── web/
│   ├── app.py             # Flask dashboard: status view, folder picker, pause/resume/promote controls
│   └── templates/         # status.html, add.html, browse.html
└── main.py                 # entrypoint: loads config, runs Manager (profiles + config hot-reload) + Flask dashboard
```

Keep profile-specific logic thin (`profiles/*.py`); anything reusable across profiles (staging, integrity, promotion, logging) belongs in `engine/`.

## Config format (`config/folders.yaml`, implemented: `engine/config.py`)

```yaml
folders:
  - path: /srv/hotdata/documents
    profile: hot_data
    versions_to_keep: 5

  - profile: wechat_vault
    staging_path: /srv/wechat/staging
    vault_path: /srv/vault/wechat
    promote_interval_minutes: 60
    keep_failed_staging: true
```

- `profile` selects behavior (`hot_data` or `wechat_vault`). `hot_data` takes `path` (+ optional `version_dir`, `versions_to_keep`, `paused`); `wechat_vault` takes `staging_path` + `vault_path` (+ optional `promote_interval_minutes`, `keep_failed_staging`) — see the deviation note above for why these differ from the original single-`path` example.
- `paused` (hot_data only, default false, Milestone 8): set by the dashboard's Pause/Resume buttons via `engine.config.set_paused()`, which matches the entry by comparing `Path(entry["path"])` to the target — not raw string equality, since the YAML might use forward slashes while a path built from a live config object renders with the OS's own separator (backslashes on Windows) and a naive string compare would silently fail to find the entry.
- `load_config()` returns a list of `HotDataFolderConfig`/`WeChatVaultFolderConfig`. An unrecognized `profile` skips that entry with a warning; an unknown key for a known profile is warned about but doesn't stop that entry from loading; a missing *required* key skips that entry with a warning. None of these raise — a bad `folders.yaml` degrades to "fewer folders managed," not a crash.
- Folders are addable/removable without restarting the app: `main.py`'s `Manager.reload()` diffs the parsed config against currently-running Hot Data profiles (stopping removed ones, starting new ones) and always rebuilds the WeChat Vault profile dict (cheap — it holds no running thread). `main.py` watches `folders.yaml` itself (via `engine/watcher.py`, reused) and calls `reload()` on change, so hand-editing the file live works today, ahead of any UI. **Known gap**: only add/remove is live — changing settings (e.g. `versions_to_keep`) on a folder that's already running is not picked up until restart, since `reload()` only diffs on path, not full config equality.

## Profile behavior

### Hot Data (implemented: `profiles/hot_data.py`)
- Watches continuously via `engine/watcher.py`; on change, checksums via `engine/checksum.py` and logs immediately — no staging delay (low corruption risk for plain files).
- **Decided**: this app does not perform cross-machine file transport itself — it supervises/assumes Syncthing (or similar) is already syncing the same folder path between machines. `HotDataProfile` only watches, checksums, logs, and versions; it never copies bytes to another host. A natural follow-up (not yet built) is querying Syncthing's local REST API to surface real sync status on the dashboard (Milestone 6+) instead of just "we saw a local change."
- Keeps the last N versions of changed files (`versions_to_keep`, read from `folders.yaml` since Milestone 5) in a sibling `<folder>.versions` directory for basic rollback. The version directory **must** live outside the watched tree — `HotDataProfile.__init__` raises if it doesn't, since a version store nested inside the watched folder would make the watcher recurse into its own snapshots.
- Snapshots are deduplicated by content checksum, not just event type: some watcher backends (confirmed on Windows) fire duplicate create+modify events for a single write, and versioning on raw event count instead of actual content change wastes rollback slots on identical copies.

### WeChat Vault
- Never write directly to the live vault path — the active machine's WeChat client writes to a separate staging copy instead.
- Promotion is meant to run on a schedule (`promote_interval_minutes`) or an explicit trigger (logout event, manual "Promote now"). The manual trigger is implemented: the dashboard's "Promote now" button (Milestone 8) calls `WeChatVaultProfile.promote_now(machine_id)` (`profiles/wechat_vault.py`, Milestone 4), which wraps `engine.staging.promote()` (Milestone 3). Runs synchronously in the Flask request thread — acceptable for a manual, infrequent, one-at-a-time action; if the vault ever gets large enough that `copytree` makes a click visibly hang the page, move it to a background thread. There is still no `engine/scheduler.py` and nothing calls `promote_now()` on an interval or on logout — only a human clicking the button triggers it.
  1. Run the integrity check against staging — `profiles/wechat_vault.py` binds `engine.integrity.wechat_vault_integrity_check` (with the live vault as `last_good_path`) via `functools.partial` before handing it to `promote()`, so `staging.py` itself stays check-agnostic (`IntegrityCheck = Callable[[Path], IntegrityResult]`, unchanged since Milestone 3). `engine.integrity.basic_integrity_check` still exists as a minimal exists/non-empty check for other testing.
  2. Pass → atomic promote: copy staging to `<vault>.new`, then swap it into place. **Implementation note**: a single `os.rename()` can't drop a directory onto an existing non-empty one (POSIX requires the target be empty), so the swap is two renames — move the live vault to `<vault>.old-<timestamp>`, rename `<vault>.new` into the vault's place, then delete the old backup. Each rename is atomic; the instant between the two renames where the vault path briefly doesn't exist is a known, accepted residual gap (not fully atomic end-to-end). A symlink-indirection swap would close that gap but was deliberately not used, since it would make the Samba-served vault path a symlink and that interaction hasn't been verified on the target Debian/Samba setup.
  3. Fail → vault is left untouched (never written to); if `keep_failed_staging` (default true), the current staging dir is copied to `<staging>.failed-<timestamp>` for inspection — the live `staging` path itself is never moved or deleted, since WeChat keeps writing there.
- Single-writer is a sanity check, not a hard lock (implemented in `engine/staging.py`): each promotion records `{machine, promoted_at}` to `<vault>.promotion-state.json`; if the next promotion comes from a different machine, it's logged as a warning, not blocked. WeChat's own single-login restriction is the real guard against concurrent writes.

### Integrity check (`engine/integrity.py`, implemented: `wechat_vault_integrity_check`)
- SQLite files are found by content sniffing (`SQLite format 3\x00` header magic), not by extension — WeChat's actual on-disk file naming isn't verified, so guessing extensions like `.db` would be fragile. Each one found is checked with `PRAGMA integrity_check;` via a read-only `sqlite3` URI connection (`file:...?mode=ro`).
- **Header-sniffing blind spot, closed**: if a file's own magic header gets corrupted (not just its body), header-sniffing alone stops recognizing it as SQLite at all — it would silently skip the file as "not a database, nothing to check" instead of flagging it, which is exactly backwards for a corruption-prevention tool. Found this via testing (a test that corrupted bytes 10–59 of a file, overlapping the 16-byte header, passed when it should have failed). Fixed: when `last_good_path` is available, any file that WAS a valid SQLite database there but no longer has a valid header in staging is flagged directly, without needing `PRAGMA integrity_check` to run at all. Residual gap: on the very first-ever promotion (no `last_good_path` to compare against), a file with an already-corrupted header from the start is indistinguishable from a file that was never a database, so it can't be flagged — there's no baseline to know what it "should" be.
- If a `last_good_path` is given (the profile passes the current live vault, when it exists), also compares file count/total size against it and fails if either drops by more than `max_drop_ratio` (default 0.2 = 20%) — a deliberately chosen starting heuristic, not a spec-mandated number; tune it if it proves too strict/loose in practice.
- Flags any file that is now zero bytes but had non-zero size in `last_good_path` at the same relative path (a newly-truncated file) — a brand-new zero-byte file with no prior counterpart is not flagged, since that could be a normal new WeChat-created file and there's no baseline to call it a regression.
- Without a `last_good_path` (first-ever promotion), only the SQLite check runs — there's nothing yet to compare counts/sizes against.
- Same `IntegrityResult(ok, reason)` shape as `basic_integrity_check`, so `engine/staging.py` never needs to know which check is plugged in.

## Web dashboard
- **Stack decided: Flask**, not FastAPI — this is a server-rendered status page with plain HTML forms (folder picker, pause/resume/promote controls), which is exactly Flask's `render_template()` sweet spot; FastAPI's strengths (async, pydantic request models, auto OpenAPI docs) aren't used by anything this dashboard needs to do.
- Status view per managed folder (implemented, Milestone 6): profile, path(s), detail, last activity time, status. `Manager.status()` in `main.py` builds this from live profile state — `HotDataProfile.last_event_at/last_event_type` and `WeChatVaultProfile.last_attempt_at/last_result`, both added in Milestone 6 since nothing previously retained queryable state (profiles only logged). Status is `ok` / `failed` / `unknown` (`unknown` = no promotion attempted yet, an honest state given there's no scheduler); Hot Data has no failure mode yet so it's always `ok` once running. `warning` is reserved in the CSS but nothing currently produces it.
- `main.py` runs the dashboard via `app.run(..., threaded=True)` in place of the old `while True: sleep` loop — the file watcher and config watcher keep running on their own threads (watchdog's `Observer`) underneath it. `TEMPLATES_AUTO_RELOAD` is explicitly enabled in `web/app.py`, since Flask does NOT reload Jinja templates from disk by default when `debug` is off — without it, editing `status.html` while the app is running has no effect until restart (found this the hard way while building the page).
- Table CSS uses `table-layout: fixed` with percentage `<col>` widths and `box-sizing: border-box`, deliberately — without `border-box`, cell padding adds on top of the percentage widths and pushes the last column (Status, the one column that most needs to stay visible) off-screen. Confirmed in the browser with real long Windows paths, not just short example paths.
- **Folder picker (implemented, Milestone 7)**: `/add` renders two separate mini-forms (Hot Data, WeChat Vault) rather than one dynamic form that shows/hides fields — avoids needing any JS at all, consistent with the rest of the dashboard. `/browse?path=...&target=<field_name>` lists subdirectories of `path` (starting at `Path.home()` if none given) with plain links to navigate; a file-picker jail wasn't added, since "browse the server's filesystem" is explicitly in scope and the app's whole security model is "no auth, trust the tailnet" (see Explicit non-goals) — this isn't a gap, it's the accepted boundary.
  - **State carries through browsing via query params, not JS or sessions**: every "Browse…" link on `/add` includes the form's other current field values as query params; `/browse` forwards them unchanged on every navigation link and folds the chosen path into them (under the `target` field's name) on the "Use this folder" link back to `/add`. This means browsing for `vault_path` after already filling `staging_path` doesn't lose `staging_path` — verified in the browser by filling one field, browsing for the other, and confirming both survived to submission. Known simplification: the `keep_failed_staging` checkbox is NOT carried through a browse round-trip (HTML checkboxes only submit when checked, making "unchecked" and "not carried" indistinguishable without extra hidden-field plumbing) — it always resets to checked (its default) when `/add` renders, whether fresh or returning from `/browse`.
  - Both add-folder forms validate before writing: path(s) must be non-empty and exist as real directories (checked with `Path.is_dir()`), numeric fields must parse as positive integers, and `staging_path != vault_path` is enforced directly — letting those through would send `engine/staging.py`'s atomic-swap logic into copying a directory into itself. All validation failures redirect back to `/add` with an `error` message and the submitted values preserved, rather than losing the user's input or crashing.
  - `engine/config.py:append_folder()` does a full read-modify-write of `folders.yaml` via `yaml.safe_dump` — this reformats the whole file and will NOT preserve hand-added comments if you mix hand-editing with using the dashboard. Known, accepted tradeoff, not an oversight.
  - **Found and fixed while testing this**: `Manager.reload()` called `HotDataProfile.start()` unguarded, which calls straight through to watchdog's `Observer.schedule()` — confirmed empirically that this raises `FileNotFoundError` immediately if the path doesn't exist. Before Milestone 7 this only mattered for hand-typed YAML typos; the add-folder form makes bad paths from users more likely, so `Manager.reload()` now catches `OSError` per-folder, logs an error, and skips just that folder instead of taking down the whole reload (and therefore hot-reload for every other folder too).
  - **Known, accepted timing quirk**: submitting either add-folder form redirects straight to `/`, but the config-file write and the watcher-thread-driven `reload()` it triggers happen asynchronously (also double-firing on Windows, same duplicate-event behavior noted for Hot Data in Milestone 2) — so the very first render of `/` after submitting can occasionally still show the old list for a moment. Confirmed self-healing on any subsequent reload (including the page's own 10s auto-refresh); not fixed, since doing so would mean blocking the request on the watcher thread for a race that already resolves itself.
- **Manual controls (implemented, Milestone 8)**: each status row gets a one-button form in a new Actions column — "Pause"/"Resume" for Hot Data (`POST /folders/hot_data/{pause,resume}`, form field `path`), "Promote now" for WeChat Vault (`POST /folders/wechat_vault/promote`, form field `staging_path`). All three verified via actual browser clicks (not just curl): Pause confirmed to truly stop the watcher (a write during pause produced zero log output), Resume confirmed to pick up a subsequent write, Promote now confirmed to update status from `unknown` to `ok` with a real integrity-check reason string.
  - **Pause/Resume was deliberately NOT added for WeChat Vault.** There's no scheduler yet, so there's nothing running to pause — a pause button that doesn't suspend anything would be a lie. Add it when `engine/scheduler.py` exists and actually calls `promote_now()` on an interval.
  - Pausing a Hot Data folder sets `paused: true` in `folders.yaml` (persists across restarts, unlike an in-memory-only flag) and fully stops+discards its `HotDataProfile`/watchdog `Observer` — `Observer` is a `Thread` subclass and can't be restarted once stopped, so Resume always constructs a fresh `HotDataProfile` rather than reusing the old one. Its last-known `last_event_at`/`last_event_type` are copied out into `Manager._hot_data_last_known` before the profile is discarded, so the status row still shows when it was last active while paused, instead of going blank.
  - `Manager.status()` now enumerates Hot Data rows from `Manager._hot_data_configs` (everything in the config, running or not) rather than only from `_hot_data_profiles` (only what's currently running) — needed so a paused folder still has a row to click Resume on.
  - "Promote now" runs synchronously and blocks the request until the copy+integrity-check finishes (see the WeChat Vault section above).
  - **Found and fixed while building this**: adding a 6th (Actions) column and shrinking `col.profile` to fit it reintroduced the Milestone-6 overflow bug in a new form — at 7% width, `overflow-wrap: break-word` broke "hot_data" and even the "PROFILE" header into single-letter-per-line stacks, because profile names are one unbroken word with no space to wrap at instead of breaking mid-word. Fixed by widening that column back to a safe width and adding a `.profile-cell { white-space: nowrap; }` rule (initially scoped to `td.profile-cell` only, which missed the `<th>` — the header still wrapped until the selector was broadened to bare `.profile-cell`).
- Reachable over Tailscale from any device; no auth beyond tailnet membership planned for v1. Currently bound to `0.0.0.0` with no auth at all — fine for local/tailnet-only testing, but don't expose port 8420 beyond the tailnet.

## Alerting (implemented: `engine/alerting.py`)
- **Notification**: `send_alert(message)` POSTs the raw message body to the URL in the `SYNC_MANAGER_NTFY_URL` env var — the shape ntfy.sh (and many plain webhook receivers) expect. No env var set → logs "not sent" and returns; never raises, so a bad or unreachable alert endpoint can't take down a promotion attempt (verified by pointing it at a refused connection and confirming `promote()` still returns normally). There's no global settings file yet, so an env var is the simplest place for one deployment-wide value — introduce a real global-config mechanism only if a second such setting shows up. A JSON-payload sink (Slack/Discord-style incoming webhooks want `{"text": ...}`, not a raw body) is the natural next pluggable option but wasn't built, since nothing in this project needs it yet. Email is explicitly a later option per the original notes.
- Wired into exactly one place: `engine.staging.promote()` calls `send_alert()` when the integrity check fails, right before returning `PromotionResult(promoted=False, ...)` — this covers both "integrity check failure" and "skipped promotion" from the spec, since in the current implementation a skipped promotion always means the check just failed (there's no other reason `promote()` skips one yet). No rate-limiting/deduplication: not needed while promotion is manual-only (Milestone 8's button) — revisit once a scheduler can retry automatically and might otherwise alert every single time on a folder that's stuck failing.
- Hot Data has no alert wiring — it has no failure mode to alert on (see Hot Data, above), so there's nothing to notify about yet.
- **Persistent logging**: `engine/logger.py`'s `get_logger()` now attaches a `RotatingFileHandler` (5 MB × 3 backups) at `logs/sync-manager.log` (project-relative; `logs/` is gitignored) alongside the existing stdout handler, using the same formatter — so every log line already going to the console (including every promotion attempt's pass/fail/timestamp/machine, already logged by `engine/staging.py` since Milestone 3) is now also captured to disk automatically. This persists everything through the shared logger, not just promotion lines specifically — broader than the spec's literal wording but simpler than routing promotion logs through a second, separate mechanism.

## Suggested stack (from planning notes)
Python backend. `watchdog` (file watching), `PyYAML` (config), and `Flask` (dashboard) are installed and pinned in `requirements.txt`; `sqlite3` (integrity checks) is stdlib. Still to be picked and added when its milestone arrives: `APScheduler` (interval-based promotion — not yet scheduled anywhere, see the WeChat Vault and Development commands notes).

## Build order (implement in this sequence)
1. Core watcher + checksum logic, no staging — detect and log changes in a test folder.
2. Hot Data profile end-to-end (simplest full path).
3. Generic staging + atomic promote logic (not yet SQLite-aware).
4. SQLite-aware integrity check plugged into the WeChat Vault profile.
5. Config loading + folder-to-profile assignment (hand-edit YAML, no UI yet).
6. Minimal web dashboard: status view only.
7. Folder picker + profile assignment in the dashboard.
8. Manual "Promote now" / pause controls.
9. Alerting on failure.

## Explicit non-goals (v1)
- Not replacing Samba/network transport — this app only manages files already present via the network share.
- Not solving cross-device conflict resolution for Hot Data beyond basic versioning (assumes Syncthing or similar handles transport/merge if used underneath).
- Not building dashboard authentication — relies on Tailscale network isolation.

## Development commands

```
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell; use `source .venv/bin/activate` on Debian
pip install -r requirements.txt
python main.py [path-to-folders.yaml]   # defaults to config/folders.yaml; starts all profiles, hot-reloads on config edits
# dashboard: http://localhost:8420/ (port is the DASHBOARD_PORT constant in main.py)
# logs: logs/sync-manager.log (rotating, gitignored) in addition to stdout
# optional: set SYNC_MANAGER_NTFY_URL to a ntfy.sh topic URL (or similar) to enable failure alerts
```

`WeChatVaultProfile.promote_now()` is reachable from the running app via the dashboard's "Promote now" button (Milestone 8). Nothing calls it *automatically* yet, though — there's still no `engine/scheduler.py`, so `promote_interval_minutes` in `folders.yaml` isn't acted on and promotion never happens on its own.

No lint or test tooling is configured yet — add it here once it exists rather than assuming a convention.
