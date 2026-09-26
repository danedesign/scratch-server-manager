import time
from pathlib import Path

from flask import Flask, redirect, render_template, request, url_for

from engine.config import append_folder, set_paused

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
            staging_path=request.args.get("staging_path", ""),
            vault_path=request.args.get("vault_path", ""),
            promote_interval_minutes=request.args.get("promote_interval_minutes", "60"),
            error=request.args.get("error", ""),
        )

    @app.route("/add/hot_data", methods=["POST"])
    def add_hot_data():
        path = request.form.get("path", "").strip()
        versions_raw = request.form.get("versions_to_keep", "5").strip()

        if not path:
            return redirect(url_for("add_folder_form", error="Path is required", versions_to_keep=versions_raw))
        if not Path(path).is_dir():
            return redirect(url_for("add_folder_form", error=f"{path} is not an existing directory", path=path, versions_to_keep=versions_raw))
        try:
            versions_to_keep = int(versions_raw)
            if versions_to_keep < 1:
                raise ValueError
        except ValueError:
            return redirect(url_for("add_folder_form", error="Versions to keep must be a positive integer", path=path, versions_to_keep=versions_raw))

        append_folder(manager.config_path, {
            "profile": "hot_data",
            "path": path,
            "versions_to_keep": versions_to_keep,
        })
        return redirect(url_for("status"))

    @app.route("/add/wechat_vault", methods=["POST"])
    def add_wechat_vault():
        staging_path = request.form.get("staging_path", "").strip()
        vault_path = request.form.get("vault_path", "").strip()
        interval_raw = request.form.get("promote_interval_minutes", "60").strip()
        keep_failed_staging = request.form.get("keep_failed_staging") == "on"

        def back(error: str):
            return redirect(url_for(
                "add_folder_form",
                error=error,
                staging_path=staging_path,
                vault_path=vault_path,
                promote_interval_minutes=interval_raw,
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

        append_folder(manager.config_path, {
            "profile": "wechat_vault",
            "staging_path": staging_path,
            "vault_path": vault_path,
            "promote_interval_minutes": promote_interval_minutes,
            "keep_failed_staging": keep_failed_staging,
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

    @app.route("/browse")
    def browse():
        target = request.args.get("target", "path")
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

        select_params = {k: v for k, v in request.args.items() if k not in ("path", "target")}
        select_params[target] = str(current)

        parent = current.parent
        return render_template(
            "browse.html",
            current=current,
            parent_url=nav_url(parent) if parent != current else None,
            entries=[(p.name, nav_url(p)) for p in entries],
            error=error,
            select_url=url_for("add_folder_form", **select_params),
        )

    return app
