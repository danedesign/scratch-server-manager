# TRACKER.md

Where the project actually stands, right now. Unlike `TIMELINE.md` (an
append-only history log — what happened, in order) this file is a live
snapshot — **update it in place** as items change status, don't just add
to it. `CLAUDE.md` has the technical detail behind any item here.

Legend: ✅ done & verified · 🔶 partially done · ⬜ not started · 🚫 blocked/unknown, needs an answer before work can start

---

## Live deployment status

**In real use as of 2026-09-27**, not just verified against test fixtures. `sync-manager.service` and `syncthing@dane` both run as persistent systemd services on the Debian VM. A real WeChat client on a Windows 11 PC (`C:\Users\DL-Work\Documents\xwechat_files`) is paired via Syncthing (PC: Send Only → VM `staging_path` `/home/dane/wechat-staging`: Receive Only, enforced one-way in both directions so staging can never write back to the live WeChat client) to the VM's `wechat_vault` profile, auto-promoting every 30 minutes into the Samba-shared vault at `/srv/samba/wechat-vault/vaultdata`. First real promotion: 318 synced files, integrity check passed, 319 files confirmed in the vault afterward. `config/folders.yaml` on the VM now holds this real entry and is gitignored (see Post-v1 additions) rather than the placeholder that used to be tracked in git.

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
- ✅ Persistent deployment via `systemd` (`deploy/sync-manager.service`) — verified surviving a `kill -9` and registered for start-on-boot on the real Debian VM
- ✅ **Two real machines promoting to the same vault, verified with genuinely separate hardware** — a macOS laptop over Tailscale, not just another VM on the same host, mounting the Debian VM's Samba vault share directly; the single-writer sanity check warned correctly in both directions without ever blocking a promotion
- ✅ Dashboard UI for editing an existing folder's settings (`/folders/{hot_data,wechat_vault}/edit`) — verified live in a real browser, including the folder-browse picker round-trip
- ✅ CI running the test suite automatically (`.github/workflows/tests.yml`) — runs `pytest` on every push/PR to `main`; verified with a real GitHub Actions run, not just the YAML being plausible: all 89 tests passed in 25s
- ✅ **WeChat staging topology decided**: `staging_path` must be local disk on whichever machine is logged into WeChat, never a Samba/CIFS mount (the CIFS/SQLite locking finding from Samba testing made this a real requirement, not a style preference) — getting it onto the Debian host is left to something transport-level underneath (Syncthing, rsync, etc.), the same assumption Hot Data already makes. `vault_path` has no such restriction and was verified as a Samba mount, including across two real machines. Documented in `CLAUDE.md`'s Config format section; no code change needed since this app never writes SQLite itself.
- ✅ **Syncthing status integration for Hot Data** (`engine/syncthing.py`, optional `syncthing_folder_id` per folder) — verified against a real Syncthing instance installed on the Debian VM, not a stub: dashboard correctly showed `syncthing: idle`, and a rescan after a real file write correctly updated the reflected state.
- ✅ `config/folders.yaml` untracked from git (a real deployment's folder list can contain real personal paths) — `config/folders.yaml.example` is the tracked placeholder now

## Open items, priority-ranked by risk (not by effort)

| # | Item | Status | Why it matters |
|---|------|--------|-----------------|
| 1 | Logout-event promotion trigger | ⬜ Not started, deliberately deferred | Platform-specific, no way to test it from this dev environment. |

## Recommended next step

Every build-order milestone and every requested post-v1 addition is now done and verified against the real Debian target. The only open item is the logout-event trigger (#1), deliberately deferred since it's platform-specific and untestable from this dev environment — pick it up only if/when a way to test it (or the user's actual OS logout behavior) becomes available. Otherwise this project is in a stable, fully-verified state; future work should come from new user requests rather than this list.

## Maintaining this file

- Move an item between sections / flip its status icon as it actually changes — this file should always answer "where are we right now" in under a minute of reading.
- New open items go into the priority table, ranked by *risk if left undone*, not by how easy they'd be to build.
- Append a one-liner to `TIMELINE.md` too whenever an item here flips to ✅ — that's the historical record; this file is the live one.
