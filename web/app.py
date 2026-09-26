import time
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

from engine.config import (
    HotDataFolderConfig,
    WeChatVaultFolderConfig,
    append_folder,
    load_config,
    set_paused,
    update_folder,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def create_app(manager) -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    @app.route("/")
    def status():
        return render_template(
            "status.html",
            rows=manager.status(),
            generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    @app.route("/add")
    def add_folder_form():
        return render_template(
            "add.html",
            path=request.args.get("path", ""),
            versions_to_keep=request.args.get("versions_to_keep", "5"),
            syncthing_folder_id=request.args.get("syncthing_folder_id", ""),
            staging_path=request.args.get("staging_path", ""),
            vault_path=request.args.get("vault_path", ""),
            promote_interval_minutes=request.args.get("promote_interval_minutes", "60"),
            wv_syncthing_folder_id=request.args.get("wv_syncthing_folder_id", ""),
            error=request.args.get("error", ""),
        )

    @app.route("/add/hot_data", methods=["POST"])
    def add_hot_data():
        path = request.form.get("path", "").strip()
        versions_raw = request.form.get("versions_to_keep", "5").strip()
        syncthing_folder_id = request.form.get("syncthing_folder_id", "").strip()

        def back(error: str):
            return redirect(url_for(
                "add_folder_form", error=error, path=path,
                versions_to_keep=versions_raw, syncthing_folder_id=syncthing_folder_id,
            ))

        if not path:
            return back("Path is required")
        if not Path(path).is_dir():
            return back(f"{path} is not an existing directory")
        try:
            versions_to_keep = int(versions_raw)
            if versions_to_keep < 1:
                raise ValueError
        except ValueError:
            return back("Versions to keep must be a positive integer")

        entry = {
            "profile": "hot_data",
            "path": path,
            "versions_to_keep": versions_to_keep,
        }
        if syncthing_folder_id:
            entry["syncthing_folder_id"] = syncthing_folder_id
        append_folder(manager.config_path, entry)
        return redirect(url_for("status"))

    @app.route("/add/wechat_vault", methods=["POST"])
    def add_wechat_vault():
        staging_path = request.form.get("staging_path", "").strip()
        vault_path = request.form.get("vault_path", "").strip()
        interval_raw = request.form.get("promote_interval_minutes", "60").strip()
        keep_failed_staging = request.form.get("keep_failed_staging") == "on"
        syncthing_folder_id = request.form.get("syncthing_folder_id", "").strip()

        def back(error: str):
            return redirect(url_for(
                "add_folder_form",
                error=error,
                staging_path=staging_path,
                vault_path=vault_path,
                promote_interval_minutes=interval_raw,
                wv_syncthing_folder_id=syncthing_folder_id,
            ))

        if not staging_path or not vault_path:
            return back("Both staging and vault paths are required")
        if not Path(staging_path).is_dir():
            return back(f"{staging_path} is not an existing directory")
        if Path(staging_path).resolve() == Path(vault_path).resolve():
            return back("Staging and vault paths must be different")
        try:
            promote_interval_minutes = int(interval_raw)
            if promote_interval_minutes < 1:
                raise ValueError
        except ValueError:
            return back("Promote interval must be a positive integer")

        entry = {
            "profile": "wechat_vault",
            "staging_path": staging_path,
            "vault_path": vault_path,
            "promote_interval_minutes": promote_interval_minutes,
            "keep_failed_staging": keep_failed_staging,
        }
        if syncthing_folder_id:
            entry["syncthing_folder_id"] = syncthing_folder_id
        append_folder(manager.config_path, entry)
        return redirect(url_for("status"))

    @app.route("/folders/hot_data/edit")
    def edit_hot_data_form():
        path = request.args.get("path", "")
        cfg = next(
            (c for c in load_config(manager.config_path) if isinstance(c, HotDataFolderConfig) and str(c.path) == path),
            None,
        )
        if cfg is None:
            return redirect(url_for("status"))
        return render_template(
            "edit_hot_data.html",
            path=str(cfg.path),
            versions_to_keep=request.args.get("versions_to_keep", str(cfg.versions_to_keep)),
            syncthing_folder_id=request.args.get("syncthing_folder_id", cfg.syncthing_folder_id or ""),
            error=request.args.get("error", ""),
        )

    @app.route("/folders/hot_data/edit", methods=["POST"])
    def edit_hot_data():
        path = request.form.get("path", "").strip()
        versions_raw = request.form.get("versions_to_keep", "").strip()
        syncthing_folder_id = request.form.get("syncthing_folder_id", "").strip()

        def back(error: str):
            return redirect(url_for(
                "edit_hot_data_form", error=error, path=path,
                versions_to_keep=versions_raw, syncthing_folder_id=syncthing_folder_id,
            ))

        try:
            versions_to_keep = int(versions_raw)
            if versions_to_keep < 1:
                raise ValueError
        except ValueError:
            return back("Versions to keep must be a positive integer")

        update_folder(manager.config_path, "hot_data", "path", path, {
            "versions_to_keep": versions_to_keep,
            "syncthing_folder_id": syncthing_folder_id or None,
        })
        return redirect(url_for("status"))

    @app.route("/folders/wechat_vault/edit")
    def edit_wechat_vault_form():
        staging_path = request.args.get("staging_path", "")
        cfg = next(
            (c for c in load_config(manager.config_path) if isinstance(c, WeChatVaultFolderConfig) and str(c.staging_path) == staging_path),
            None,
        )
        if cfg is None:
            return redirect(url_for("status"))
        return render_template(
            "edit_wechat_vault.html",
            staging_path=str(cfg.staging_path),
            vault_path=request.args.get("vault_path", str(cfg.vault_path)),
            promote_interval_minutes=request.args.get("promote_interval_minutes", str(cfg.promote_interval_minutes)),
            keep_failed_staging=cfg.keep_failed_staging,
            syncthing_folder_id=request.args.get("syncthing_folder_id", cfg.syncthing_folder_id or ""),
            error=request.args.get("error", ""),
        )

    @app.route("/folders/wechat_vault/edit", methods=["POST"])
    def edit_wechat_vault():
        staging_path = request.form.get("staging_path", "").strip()
        vault_path = request.form.get("vault_path", "").strip()
        interval_raw = request.form.get("promote_interval_minutes", "").strip()
        keep_failed_staging = request.form.get("keep_failed_staging") == "on"
        syncthing_folder_id = request.form.get("syncthing_folder_id", "").strip()

        def back(error: str):
            return redirect(url_for(
                "edit_wechat_vault_form",
                error=error,
                staging_path=staging_path,
                vault_path=vault_path,
                promote_interval_minutes=interval_raw,
                syncthing_folder_id=syncthing_folder_id,
            ))

        if not vault_path:
            return back("Vault path is required")
        if Path(staging_path).resolve() == Path(vault_path).resolve():
            return back("Staging and vault paths must be different")
        try:
            promote_interval_minutes = int(interval_raw)
            if promote_interval_minutes < 1:
                raise ValueError
        except ValueError:
            return back("Promote interval must be a positive integer")

        update_folder(manager.config_path, "wechat_vault", "staging_path", staging_path, {
            "vault_path": vault_path,
            "promote_interval_minutes": promote_interval_minutes,
            "keep_failed_staging": keep_failed_staging,
            "syncthing_folder_id": syncthing_folder_id or None,
        })
        return redirect(url_for("status"))

    @app.route("/folders/hot_data/pause", methods=["POST"])
    def pause_hot_data():
        set_paused(manager.config_path, "hot_data", "path", request.form.get("path", ""), True)
        return redirect(url_for("status"))

    @app.route("/folders/hot_data/resume", methods=["POST"])
    def resume_hot_data():
        set_paused(manager.config_path, "hot_data", "path", request.form.get("path", ""), False)
        return redirect(url_for("status"))

    @app.route("/folders/wechat_vault/pause", methods=["POST"])
    def pause_wechat_vault():
        set_paused(manager.config_path, "wechat_vault", "staging_path", request.form.get("staging_path", ""), True)
        return redirect(url_for("status"))

    @app.route("/folders/wechat_vault/resume", methods=["POST"])
    def resume_wechat_vault():
        set_paused(manager.config_path, "wechat_vault", "staging_path", request.form.get("staging_path", ""), False)
        return redirect(url_for("status"))

    @app.route("/folders/wechat_vault/promote", methods=["POST"])
    def promote_wechat_vault():
        profile = manager.wechat_vault_profiles.get(Path(request.form.get("staging_path", "")))
        if profile is not None:
            profile.promote_now()
        return redirect(url_for("status"))

    @app.route("/folders/wechat_vault/verify", methods=["POST"])
    def verify_wechat_vault():
        manager.verify_wechat_vault(Path(request.form.get("staging_path", "")))
        return redirect(url_for("status"))

    @app.route("/browse")
    def browse():
        target = request.args.get("target", "path")
        return_to = request.args.get("return_to", "add_folder_form")
        current = Path(request.args.get("path") or Path.home())

        error = None
        if not current.is_dir():
            error = f"{current} is not a directory or is not accessible"
            current = Path.home()

        entries = []
        if error is None:
            try:
                entries = sorted((p for p in current.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
            except OSError as exc:
                error = str(exc)

        carry_params = {k: v for k, v in request.args.items() if k != "path"}

        def nav_url(p: Path) -> str:
            return url_for("browse", path=str(p), **carry_params)

        select_params = {k: v for k, v in request.args.items() if k not in ("path", "target", "return_to")}
        select_params[target] = str(current)

        parent = current.parent
        return render_template(
            "browse.html",
            current=current,
            parent_url=nav_url(parent) if parent != current else None,
            entries=[(p.name, nav_url(p)) for p in entries],
            error=error,
            select_url=url_for(return_to, **select_params),
        )

    return app
