# TRACKER.md

Where the project actually stands, right now. Unlike `TIMELINE.md` (an
append-only history log — what happened, in order) this file is a live
snapshot — **update it in place** as items change status, don't just add
to it. `CLAUDE.md` has the technical detail behind any item here.

Legend: ✅ done & verified · 🔶 partially done · ⬜ not started · 🚫 blocked/unknown, needs an answer before work can start

---

## v1 scope (original 9 build-order milestones)

All ✅ done. Core watcher/checksum engine, Hot Data (versioned rollback), WeChat Vault (staged + SQLite-integrity-checked + atomically promoted), config loading with hot-reload, Flask dashboard, folder picker, manual controls, persistent logging + pluggable alerting.

## Post-v1 additions (all requested directly, all done)

- ✅ Automatic WeChat Vault promotion on a schedule (`engine/scheduler.py`)
- ✅ Real Pause/Resume for WeChat Vault (not just Hot Data)
- ✅ `pytest` suite — 75 tests, all passing on Windows *and* real Debian
- ✅ Hot Data live settings-editing (no restart needed)
- ✅ **Verified end-to-end on real Debian 13**, over real Tailscale — including WeChat Vault's atomic promotion actually executed on real ext4 through the live dashboard, with the resulting database confirmed byte-for-byte intact
- ✅ **Real WeChat data checked and handled — confirmed encrypted (SQLCipher), integrity checker updated and verified against it.** Every `.db`/`.kvdb` file in a real WeChat Linux client vault (`db_storage/{message,contact,session,...}`) is SQLCipher-encrypted — `file` reports "data" for all of them, no plaintext header, first bytes high-entropy. The checker previously detected zero of these as databases to check at all. Deliberately does **not** attempt decryption (this tool must never have or ask for the key) — instead added a page-alignment check (SQLCipher's fixed 4096-byte pages mean a genuine file size is always an exact multiple of that) for files matching the now-*confirmed* (not guessed) real naming. Verified directly against the real vault: passes clean on the real, healthy data; correctly flags a 17-byte truncation deliberately made to a scratch *copy* (never the live vault).
- ✅ **Samba share testing — this app's own code confirmed safe over real SMB; a serious risk found in the WeChat client's own write path.** See `CLAUDE.md`'s Samba testing section for full detail. Summary: Hot Data's `inotify` watcher, version snapshotting/pruning, and WeChat Vault's atomic two-rename promote swap all work correctly over a real loopback CIFS mount on Debian — verified via the live dashboard route, not just local calls. But a real, high-severity finding: **SQLite cannot open a database for writing on this CIFS mount at all** (`database is locked`, reproducible on table creation, not just concurrent access) — this app's own code never writes SQLite directly so it's unaffected, but if a remote WeChat client's `staging_path` is itself a Samba mount (not a local disk staged separately), WeChat's own writes to its SQLite databases would fail outright. This is now the top open risk (see below), replacing the resolved Samba-testing item.

## Open items, priority-ranked by risk (not by effort)

| # | Item | Status | Why it matters |
|---|------|--------|-----------------|
| 1 | WeChat staging path must not be a direct Samba/CIFS mount | 🚫 Blocked, needs a decision | Confirmed on real Debian: SQLite fails to even create a table on a loopback CIFS mount (`database is locked`), reproducibly, not just under contention. This app's own code never writes SQLite directly so it's unaffected, but if a remote WeChat client is pointed at a `staging_path` that's itself a live Samba mount, WeChat's own writes would fail outright. Needs a decision: require `staging_path` to be a local disk path that's synced to the Samba host some other way (e.g. Syncthing, like Hot Data), or document that WeChat must never write directly over the share. Not a bug to fix in this codebase — a deployment/topology constraint to decide and document. |
| 2 | Persistent deployment (systemd unit, restart-on-crash, start-on-boot) | ✅ Done | `deploy/sync-manager.service`, installed and `enable`d on the real Debian VM. Verified: survives a `kill -9` on the main process (systemd restarted it with a new PID within seconds, dashboard reachable again), and `enable` registers it to start on boot. |
| 3 | Two real machines promoting to the same vault | ✅ Done | Verified with two genuinely separate real hosts (the Debian VM + a macOS machine, both over Tailscale), each with its own local `staging_path`, both promoting to the *same* shared vault directory over Samba (the Mac mounted the Debian VM's `wechat-vault` share via `mount_smbfs`). Single-writer sanity check fired a warning on every switch between machines, in both directions, without ever blocking a promotion — exactly as designed. Vault correctly ended up with whichever machine promoted last, integrity check stayed clean throughout. |
| 4 | Dashboard UI to edit an existing folder's settings | 🔶 Mechanism works, no UI | `Manager.reload()` picks up a settings change live; nothing in `web/` writes anything except `paused` to an existing entry. Hand-edit `folders.yaml` today. |
| 5 | Syncthing status integration for Hot Data | ⬜ Not started | Dashboard shows "watching," not real Syncthing sync state. |
| 6 | Logout-event promotion trigger | ⬜ Not started, deliberately deferred | Platform-specific, no way to test it from this dev environment. |
| 7 | CI running the test suite automatically | ⬜ Not started | Tests exist and pass; nothing runs them on push/PR yet. |

## Recommended next step

**#1 — Decide the WeChat staging topology.** Samba testing (done) surfaced a real constraint, not a code bug: this app's own file operations (copy, rename, read-only integrity checks) all work correctly over a real CIFS mount, but a remote WeChat client cannot safely write its live SQLite databases directly onto one — `sqlite3` can't take the lock it needs. Decide how a remote machine's WeChat client actually gets its files into `staging_path`: most likely, `staging_path` should be a local disk path on whichever machine is currently logged into WeChat, kept in sync to the Debian host by something transport-level (Syncthing, rsync, etc.) the same way Hot Data already assumes Syncthing underneath it — rather than WeChat writing straight to a mounted share. This is a one-line decision plus a `CLAUDE.md` clarification, not new code, unless the decision is to add a check that refuses to run WeChat Vault against a detected network filesystem.

Persistent deployment (#2) and the two-real-machines test (#3) are both done now. What remains, in order: **#1** (the topology decision above — a documentation/decision item, not code), then **#4 — a dashboard UI for editing an existing folder's settings**, since the mechanism (`Manager.reload()`) already supports it live and only the UI is missing.

## Maintaining this file

- Move an item between sections / flip its status icon as it actually changes — this file should always answer "where are we right now" in under a minute of reading.
- New open items go into the priority table, ranked by *risk if left undone*, not by how easy they'd be to build.
- Append a one-liner to `TIMELINE.md` too whenever an item here flips to ✅ — that's the historical record; this file is the live one.
