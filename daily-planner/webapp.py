"""Minimal web UI for managing the tasks the daily planner works from.

Run locally:   .venv/bin/python webapp.py   →  http://127.0.0.1:5000
In production it's served by gunicorn behind a TLS reverse proxy
(planner.urbantrends.dev). All routes require login.
"""
from __future__ import annotations

import logging
import os

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

import task_store
from config import config

log = logging.getLogger("webapp")

app = Flask(__name__)
# Trust one hop of reverse-proxy headers so scheme/host are correct behind Caddy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Session signing key. Without a stable SECRET_KEY, logins reset on restart.
app.secret_key = config.secret_key or os.urandom(32)
if not config.secret_key:
    log.warning("SECRET_KEY not set — sessions won't survive restarts.")
if not config.app_password_hash:
    log.warning("APP_PASSWORD_HASH not set — no one can log in until it is.")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.cookie_secure,  # set COOKIE_SECURE=true in prod (TLS)
)

task_store.init_db(config.tasks_db)

_PUBLIC = {"login", "static"}


def _safe_next(target: str | None) -> str:
    """Only allow same-site relative redirects (avoid open redirect)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("index")


@app.before_request
def require_login():
    if request.endpoint in _PUBLIC:
        return
    if not session.get("user"):
        return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = request.form.get("username", "")
        pw = request.form.get("password", "")
        if (user == config.app_user
                and config.app_password_hash
                and check_password_hash(config.app_password_hash, pw)):
            session["user"] = user
            session.permanent = True
            return redirect(_safe_next(request.args.get("next")))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template(
        "index.html",
        user=session.get("user"),
        open_tasks=task_store.list_tasks(config.tasks_db, status="open"),
        waiting=task_store.list_tasks(config.tasks_db, status="waiting"),
        done=task_store.list_tasks(config.tasks_db, status="done"),
        priorities=task_store.PRIORITIES,
    )


@app.post("/add")
def add():
    title = request.form.get("title", "").strip()
    if title:
        task_store.add_task(
            config.tasks_db,
            title=title,
            priority=request.form.get("priority", "normal"),
            due=request.form.get("due", ""),
            status=request.form.get("status", "open"),
        )
    return redirect(url_for("index"))


@app.post("/status/<int:task_id>")
def status(task_id: int):
    task_store.set_status(config.tasks_db, task_id, request.form.get("status", "open"))
    return redirect(url_for("index"))


@app.post("/delete/<int:task_id>")
def delete(task_id: int):
    task_store.delete_task(config.tasks_db, task_id)
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(
        host=os.getenv("WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("WEB_PORT", "5000")),
        debug=False,
    )
