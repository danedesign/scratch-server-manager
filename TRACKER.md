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

## Open items, priority-ranked by risk (not by effort)

| # | Item | Status | Why it matters |
|---|------|--------|-----------------|
| 1 | Real WeChat databases: encrypted (SQLCipher) or plain SQLite? | 🚫 **Unknown — check this first** | If encrypted, the integrity checker's header-sniffing detects nothing at all, silently. The core safety feature could be doing zero real work right now and nothing would say so. |
| 2 | Samba share testing | ⬜ Not started | The spec's whole framing is "Samba serves these shares, this app manages what's inside them" — never tested against an actual Samba mount (locking, permissions, behavior under Samba specifically). |
| 3 | Persistent deployment (systemd unit, restart-on-crash, start-on-boot) | ⬜ Not started | Right now it only runs as long as a manual SSH session keeps it alive. |
| 4 | Two real machines promoting to the same vault | ⬜ Not started | The single-writer sanity check exists exactly for this scenario, which has never actually happened in testing — only ever one machine. |
| 5 | Dashboard UI to edit an existing folder's settings | 🔶 Mechanism works, no UI | `Manager.reload()` picks up a settings change live; nothing in `web/` writes anything except `paused` to an existing entry. Hand-edit `folders.yaml` today. |
| 6 | Syncthing status integration for Hot Data | ⬜ Not started | Dashboard shows "watching," not real Syncthing sync state. |
| 7 | Logout-event promotion trigger | ⬜ Not started, deliberately deferred | Platform-specific, no way to test it from this dev environment. |
| 8 | CI running the test suite automatically | ⬜ Not started | Tests exist and pass; nothing runs them on push/PR yet. |

## Recommended next step

**#1 — check whether real WeChat data is encrypted**, before touching Samba or deployment. Cheap to check (`file /path/to/a/real/wechat/db`), and the answer determines whether the integrity checker needs real engineering work or already does its job. Building out #2/#3 first, only to find out afterward that #1 was broken the whole time, would be the expensive way to learn this.

## Maintaining this file

- Move an item between sections / flip its status icon as it actually changes — this file should always answer "where are we right now" in under a minute of reading.
- New open items go into the priority table, ranked by *risk if left undone*, not by how easy they'd be to build.
- Append a one-liner to `TIMELINE.md` too whenever an item here flips to ✅ — that's the historical record; this file is the live one.
