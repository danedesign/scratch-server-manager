# RUNBOOK.md

Step-by-step procedures for operating Sync Manager day-to-day — written for
you, not for a future Claude Code session (that's what `CLAUDE.md` is for).
`TRACKER.md` has current status, `TIMELINE.md` has history; this file has
"how do I actually do X."

---

## Accessing the dashboard

- **Browser**: `http://100.115.118.107:8420` (the Debian VM's Tailscale
  address) — works from any device signed into your Tailscale account.
- **Installed app (PWA)**: open the URL above in Edge/Chrome, click the
  install icon in the address bar (or **⋯ menu → Apps/Install this site as
  an app**), and it becomes a real Start Menu/Desktop/phone-home-screen icon
  with no address bar.
- **Native launcher (auto-discovers the host)**: download `SyncManager.exe`
  from the [latest GitHub release](https://github.com/danedesign/scratch-server-manager/releases/latest)
  onto any machine on your tailnet. Double-click it — it scans the tailnet,
  finds whichever device is running Sync Manager, and opens the dashboard
  directly. No IP/URL involved at all, and it works even if the VM's
  address ever changes.

## Deploying a code update to the VM

The service does **not** hot-reload Python code — only Jinja templates
auto-reload live. A `git pull` that changes both a template and the routes
it references can transiently break the dashboard until you restart. Always
restart after pulling:

```bash
cd ~/scratch-server-manager
git pull
sudo systemctl restart sync-manager
sleep 2
curl -s -o /dev/null -w 'dashboard http %{http_code}\n' http://localhost:8420/
```

A restart resets in-memory status (last promote result, last Verify result)
back to "unknown" until the next promote/verify runs — this is expected,
not data loss. The vault and staging data on disk are untouched.

## Adding a new Hot Data folder

Dashboard → **+ Add folder** → fill in the **Hot Data** form (folder path,
versions to keep, optional Syncthing folder ID) → **Add Hot Data folder**.
Takes effect within a few seconds via config hot-reload — no restart needed
for config-only changes (only code/template changes need a restart).

## Adding a new WeChat Vault folder (pairing a new WeChat-hosting machine)

This is the general procedure behind what we did for the current DL-Work
setup — follow it again for any additional machine that will run WeChat.

1. **Install Syncthing** on the WeChat machine and on the Debian VM (VM:
   `sudo apt install -y syncthing`, then `sudo systemctl enable --now
   syncthing@<user>`).
2. **Get each device's Syncthing ID**: its web UI → **Actions → Show ID**
   (or on the VM: `curl -s http://127.0.0.1:8384/rest/system/status -H
   "X-API-Key: <key>" | python3 -c "import json,sys;
   print(json.load(sys.stdin)['myID'])"`).
3. **Add each device as a remote device** on the other, with an explicit
   address (`tcp://<tailscale-ip>:22000`, not `dynamic` — more reliable
   over Tailscale).
4. On the **WeChat machine**: share the real WeChat data folder (find it
   via WeChat's own Settings → File Management) to the VM's device, **Folder
   Type: Send Only**.
5. On the **VM**: accept the incoming folder into a plain **local** disk
   path (e.g. `/home/dane/wechat-staging-2`) — **never a Samba/CIFS mount**
   (SQLite can't write to one at all — see `CLAUDE.md`'s Config format
   section for why). **Folder Type: Receive Only**. This one-way
   enforcement in both directions means nothing synced can ever write back
   and corrupt the live WeChat client.
6. On the dashboard, **+ Add folder** → **WeChat Vault** form: `staging_path`
   = that new local folder, `vault_path` = wherever you want it promoted
   (a Samba share is fine here), optionally the matching `syncthing_folder_id`
   for status visibility.
7. Set `SYNC_MANAGER_SYNCTHING_API_KEY` in `/etc/sync-manager.env` if not
   already set (one key covers all folders on that Syncthing instance),
   then `sudo systemctl restart sync-manager`.

## Migrating / replacing a WeChat account's local data folder

Use this whenever you need to move a real, existing WeChat history onto a
machine (e.g. importing years of history from an old PC) — **not** the
routine day-to-day sync, which just happens automatically.

1. **Temporarily pair the two machines directly** (old PC → new PC),
   bypassing the VM for this one-time bulk transfer: same Syncthing pairing
   steps as above, but share into a **new, empty temp folder** on the new
   PC (e.g. `C:\WeChatImport\`) — *not* the live WeChat folder yet. Old PC:
   Send Only. New PC: Receive Only.
2. **Wait for "Up to Date" / 0 items, 0 bytes remaining** on the receiving
   side — don't act on "looks close." Check the connection type shown in
   Syncthing's GUI is "Direct," not relayed (relayed is much slower).
   Rough transfer-time estimate: `size ÷ min(sender's upload, receiver's
   download)`, then knock off ~20-30% for real-world overhead.
3. **Close WeChat completely** on the destination machine — check Task
   Manager, not just the tray icon, to confirm the process actually exited.
   Any file lock during the swap is the main risk here.
4. **Rename (never delete) the current live folder** as a safety net, even
   if you're told it's disposable — cheap insurance for irreplaceable data:
   ```
   C:\Users\<user>\Documents\xwechat_files  →  xwechat_files.backup-<date>
   ```
5. **Move the imported folder into place** (should be instant if both are
   on the same drive, not a slow copy):
   ```
   C:\WeChatImport\  →  C:\Users\<user>\Documents\xwechat_files
   ```
6. **Reopen WeChat**, confirm it loads with the full real history.
7. The **existing** WeChat Vault pairing (that machine → VM staging) then
   picks up the change automatically and starts syncing the full amount up
   to the VM — a separate, potentially multi-hour transfer of its own.
8. Once **that** finishes, click **Verify** on the dashboard (real
   confirmation: Syncthing's block-hash completion + a fresh integrity
   check against the actual staged copy) before trusting it, then
   **Promote now** (or let the schedule catch it).
9. Only delete the step-4 backup after step 8's Verify comes back clean.

## Checking sync status / troubleshooting a stuck sync

- **Dashboard status row** is the first thing to check — it already
  combines promote status, next scheduled run, real Syncthing state
  (`syncthing: idle` / `syncing (N files remaining)`), and the last Verify
  result, all in one line.
- **Click Verify** for an on-demand, authoritative check rather than
  guessing from the passive status line.
- If Syncthing itself seems stuck (not just "hasn't been triggered yet"),
  open its own web UI (`http://127.0.0.1:8384` on whichever machine, or via
  SSH tunnel/local access — its API is intentionally not exposed over the
  network) and check: folder state, connection type (Direct vs relayed),
  and any errors listed under that folder.
- **App logs**: `logs/sync-manager.log` in the repo directory (persists
  across restarts, rotated at 5MB×3), or `sudo journalctl -u sync-manager`
  on the VM for everything including stdout/stderr.

## Windows Update: stop forced reboots without losing updates

One Administrator PowerShell command, no reboot needed to take effect:

```powershell
reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" /v NoAutoRebootWithLoggedOnUsers /t REG_DWORD /d 1 /f
```

Windows will still download/install updates and prompt you to restart, but
will never auto-restart while you're logged in — only if the machine is
sitting idle with no one signed in. Combine with **Settings → Windows
Update → Advanced options → Active hours** set to your real usage window
for extra safety margin.

## Getting the desktop launcher onto a new machine

No build step needed:

1. On the new machine (must be on the same tailnet), go to
   [github.com/danedesign/scratch-server-manager/releases/latest](https://github.com/danedesign/scratch-server-manager/releases/latest)
2. Download `SyncManager.exe`
3. Double-click it — first launch scans the tailnet (a few seconds);
   every launch after that is near-instant via its local cache.

To rebuild it yourself instead (e.g. after changing `desktop-app/launcher.py`):
see `desktop-app/README.md`.
