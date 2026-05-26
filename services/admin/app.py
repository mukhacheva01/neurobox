"""Universal web admin panel for the Telegram bot network (Flask)."""
import os

from flask import Flask, redirect, render_template, request, session, url_for

from services.admin import routes
from services.admin.access import (
    authenticate_admin,
    ensure_admin_bootstrap,
    login_required,
    role_required,
)
from services.admin.config import ADMIN_PANEL_PORT, BOT_DISPLAY_NAME, BOT_TYPE

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
_secret = os.environ.get("ADMIN_PANEL_SECRET", "").strip()
if not _secret or _secret in ("change-me-in-production", "change-me", "dev-only-change-in-production"):
    raise ValueError("ADMIN_PANEL_SECRET must be set and must not use a default value in production")
app.secret_key = _secret
app.config["ADMIN_USER"] = os.environ.get("ADMIN_PANEL_USER", "admin").strip() or "admin"
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PANEL_PASSWORD", "").strip()
if not app.config["ADMIN_PASSWORD"]:
    raise ValueError("ADMIN_PANEL_PASSWORD must be set in production")
app.config["BOT_TYPE"] = BOT_TYPE
app.config["BOT_DISPLAY_NAME"] = BOT_DISPLAY_NAME
ensure_admin_bootstrap()


@app.context_processor
def inject_bot_context():
    return {
        "bot_display_name": app.config["BOT_DISPLAY_NAME"],
        "bot_type": app.config["BOT_TYPE"],
        "admin_role": session.get("admin_role"),
        "admin_login": session.get("admin_login"),
        "role_owner": "owner",
        "role_admin": "admin",
        "role_support": "support",
        "role_viewer": "viewer",
    }


_login_attempts: dict[str, list[float]] = {}
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SEC = 900


def _login_failed_attempt(ip: str) -> None:
    import time

    now = time.monotonic()
    cutoff = now - _LOGIN_WINDOW_SEC
    attempts = _login_attempts.get(ip) or []
    attempts = [t for t in attempts if t > cutoff]
    attempts.append(now)
    _login_attempts[ip] = attempts


def _login_rate_limit_exceeded(ip: str) -> bool:
    import time

    cutoff = time.monotonic() - _LOGIN_WINDOW_SEC
    attempts = _login_attempts.get(ip) or []
    attempts = [t for t in attempts if t > cutoff]
    return len(attempts) >= _LOGIN_MAX_ATTEMPTS


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip() or "unknown"
        if _login_rate_limit_exceeded(ip):
            return render_template("login.html", error="Слишком много попыток. Подождите 15 минут.")
        user = (request.form.get("login") or request.form.get("username") or "").strip()
        password = request.form.get("password", "")
        otp = request.form.get("otp", "").strip()
        auth = authenticate_admin(user, password, otp or None)
        if auth and not auth.get("otp_required") and not auth.get("rate_limited"):
            session["admin_logged_in"] = True
            session["admin_user_id"] = auth["id"]
            session["admin_login"] = auth["login"]
            session["admin_role"] = auth["role"]
            session["admin_api_token"] = auth["token"]
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        if auth and auth.get("otp_required"):
            return render_template("login.html", error="Нужен код 2FA", otp_required=True, login_prefill=user)
        if auth and auth.get("rate_limited"):
            return render_template("login.html", error="Слишком много попыток. Подождите 15 минут.", otp_required=False, login_prefill=user)
        _login_failed_attempt(ip)
        return render_template("login.html", error="Неверный логин, пароль или код", otp_required=False, login_prefill=user)
    return render_template("login.html", error=None, otp_required=False, login_prefill="")


@app.route("/logout")
def logout():
    for key in ("admin_logged_in", "admin_user_id", "admin_login", "admin_role", "admin_api_token"):
        session.pop(key, None)
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return {"status": "ok", "bot_type": app.config["BOT_TYPE"]}


@app.route("/")
@login_required
def dashboard():
    return routes.dashboard()


app.add_url_rule("/stats", endpoint="stats", view_func=login_required(routes.stats_page))
app.add_url_rule("/users", endpoint="users_list", view_func=login_required(routes.users_list))
app.add_url_rule("/users/export", endpoint="users_export", view_func=role_required("admin", "owner")(routes.users_export))
app.add_url_rule("/user/<int:user_id>", endpoint="user_detail", view_func=login_required(routes.user_detail))
app.add_url_rule("/user/<int:user_id>/action", endpoint="user_action", view_func=role_required("admin", "owner")(routes.user_action), methods=["POST"])
app.add_url_rule("/payments", endpoint="payments_list", view_func=login_required(routes.payments_list))
app.add_url_rule("/payments/export", endpoint="payments_export", view_func=role_required("admin", "owner")(routes.payments_export))
app.add_url_rule("/errors", endpoint="errors", view_func=login_required(routes.errors_page))
app.add_url_rule("/errors/export", endpoint="errors_export", view_func=role_required("admin", "owner")(routes.errors_export))
app.add_url_rule("/audit", endpoint="audit_log", view_func=role_required("admin", "owner")(routes.audit_log))
app.add_url_rule("/feedback", endpoint="feedback_list", view_func=role_required("support", "admin", "owner")(routes.feedback_list))
app.add_url_rule("/feedback/<int:feedback_id>/action", endpoint="feedback_action", view_func=role_required("support", "admin", "owner")(routes.feedback_action), methods=["POST"])
app.add_url_rule("/content", endpoint="content_texts", view_func=role_required("admin", "owner")(routes.content_texts), methods=["GET", "POST"])
app.add_url_rule("/tariffs", endpoint="tariffs_list", view_func=role_required("admin", "owner")(routes.tariffs_list), methods=["GET", "POST"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=ADMIN_PANEL_PORT)
