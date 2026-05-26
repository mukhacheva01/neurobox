#!/usr/bin/env python3
"""Post-deploy synthetic user-flow smoke checks for NeuroBox.

This script is safe to run after deploy without a real Telegram user session.
It validates the user-facing surface that can be checked server-side:

- config + imports
- DB/Redis health (via scripts.healthcheck)
- model registry consistency guard
- Telegram Bot API reachability (getMe/getMyCommands)
- published command list matches bot/main.py declarations
- worker KPI funnel SQL smoke (read-only)

Recommended run (inside bot container):
  docker compose exec -T bot python scripts/smoke_user_flow.py

Optional contract tests (slower):
  docker compose exec -T bot python scripts/smoke_user_flow.py --with-contract-tests
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _load_env() -> None:
    for d in [os.getcwd(), "/app", "/opt/neurobox", os.path.dirname(os.path.abspath(__file__))]:
        env_path = os.path.join(d, ".env")
        if os.path.isfile(env_path):
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


_load_env()

ROOT = os.environ.get("NEUROBOX_ROOT") or ("/app" if os.path.isdir("/app") else "/opt/neurobox")
if os.path.isdir(ROOT):
    os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str
    duration_ms: int
    data: dict[str, Any] | None = None


async def _run_check(name: str, fn):
    started = time.monotonic()
    try:
        details, data = await fn()
        ok = True
    except Exception as e:
        ok = False
        details = f"{type(e).__name__}: {e}"
        data = None
    return CheckResult(
        name=name,
        ok=ok,
        details=details,
        duration_ms=int((time.monotonic() - started) * 1000),
        data=data,
    )


async def check_config() -> tuple[str, dict[str, Any]]:
    from shared.config import settings

    missing = []
    if not getattr(settings, "bot_token", ""):
        missing.append("BOT_TOKEN")
    if not getattr(settings, "bot_username", ""):
        missing.append("BOT_USERNAME")

    if missing:
        raise RuntimeError("Missing required settings: " + ", ".join(missing))

    return (
        "config loaded",
        {
            "bot_username": settings.bot_username,
            "admin_ids_count": len(getattr(settings, "admin_id_list", []) or []),
        },
    )


async def check_health() -> tuple[str, dict[str, Any]]:
    from scripts.healthcheck import check_postgres, check_redis

    pg_ok = await check_postgres()
    redis_ok = await check_redis()
    if not pg_ok:
        raise RuntimeError("postgres healthcheck failed")

    details = "pg=yes redis=yes" if redis_ok else "pg=yes redis=degraded"
    return details, {"postgres": pg_ok, "redis": redis_ok}


async def check_model_registry() -> tuple[str, dict[str, Any]]:
    from services.bot.config.model_registry_guard import validate_model_registry

    errors = validate_model_registry()
    if errors:
        raise RuntimeError(" | ".join(errors))
    return "registry ok", {"errors": 0}


def _expected_commands_from_main() -> list[str]:
    from shared.config import settings

    main_py = Path(ROOT) / "bot" / "main.py"
    src = main_py.read_text(encoding="utf-8", errors="ignore")
    cmds = re.findall(r'BotCommand\(command="([a-z0-9_]+)"', src)
    if not cmds:
        raise RuntimeError("No BotCommand declarations found in bot/main.py")
    # preserve order, drop dupes
    out: list[str] = []
    for c in cmds:
        if c not in out:
            out.append(c)

    if not bool(getattr(settings, "enable_video", False)):
        out = [c for c in out if c not in {"video", "setvideo"}]

    if not bool(getattr(settings, "enable_music", False)):
        out = [c for c in out if c not in {"music"}]

    if not bool(getattr(settings, "enable_tts", False)):
        out = [c for c in out if c not in {"voice", "settts", "setvoice", "tts"}]

    if not (getattr(settings, "serper_api_key", "") or "").strip():
        out = [c for c in out if c != "search"]

    return out


async def check_telegram_bot_api() -> tuple[str, dict[str, Any]]:
    import httpx

    from shared.config import settings

    base = f"https://api.telegram.org/bot{settings.bot_token}"
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        me_resp = await client.get(base + "/getMe")
        cmds_resp = await client.get(base + "/getMyCommands")

    me = me_resp.json()
    cmds = cmds_resp.json()
    if not me.get("ok"):
        raise RuntimeError(f"getMe failed: {me}")
    if not cmds.get("ok"):
        raise RuntimeError(f"getMyCommands failed: {cmds}")

    bot_username_live = ((me.get("result") or {}).get("username") or "").strip()
    bot_username_cfg = (getattr(settings, "bot_username", "") or "").strip().lstrip("@")
    if bot_username_cfg and bot_username_live and bot_username_live.lower() != bot_username_cfg.lower():
        raise RuntimeError(f"BOT_USERNAME mismatch: cfg={bot_username_cfg}, live={bot_username_live}")

    expected = _expected_commands_from_main()
    live_cmds = [x.get("command") for x in (cmds.get("result") or []) if x.get("command")]
    missing = [c for c in expected if c not in live_cmds]
    extras = [c for c in live_cmds if c not in expected]
    if missing:
        raise RuntimeError("Missing published commands: " + ", ".join(missing))

    return (
        f"telegram ok, commands={len(live_cmds)}",
        {
            "bot_username_live": bot_username_live,
            "expected_commands": expected,
            "live_commands": live_cmds,
            "extra_commands": extras,
        },
    )


async def check_worker_funnel_sql_smoke() -> tuple[str, dict[str, Any]]:
    from shared.db.database import get_pool
    from services.worker.main import _compute_funnel_window

    pool = await get_pool()
    async with pool.acquire() as conn:
        current = await _compute_funnel_window(conn, 24, 0)
        previous = await _compute_funnel_window(conn, 24, 24)

    for name, sample in (("current", current), ("previous", previous)):
        if not isinstance(sample, dict):
            raise RuntimeError(f"{name} funnel is not dict")
        for key in ("start", "first_generation", "paywall_hit", "purchase", "repeat"):
            if key not in sample:
                raise RuntimeError(f"{name} funnel missing key: {key}")

    return "worker funnel sql ok", {"current": current, "previous": previous}


async def check_contract_tests() -> tuple[str, dict[str, Any]]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_buttons_commands.py",
        "tests/test_smoke_release.py",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=ROOT,
    )
    out_b, _ = await proc.communicate()
    out = (out_b or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(out or f"pytest exit code {proc.returncode}")
    tail = " | ".join([line.strip() for line in out.splitlines()[-2:] if line.strip()])
    return tail or "contract tests ok", {"pytest_output": out}


def _print_human(results: list[CheckResult]) -> None:
    print("NeuroBox synthetic smoke user flow")
    print("=" * 48)
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        print(f"[{mark:<4}] {r.name:<26} {r.duration_ms:>5} ms  {r.details}")
    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    print("-" * 48)
    print(f"Summary: ok={ok_count} fail={fail_count}")


async def _amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Post-deploy synthetic user-flow smoke checks")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print JSON result")
    parser.add_argument("--skip-telegram", action="store_true", help="Skip Telegram Bot API checks")
    parser.add_argument("--skip-worker-sql", action="store_true", help="Skip worker funnel SQL smoke")
    parser.add_argument("--with-contract-tests", action="store_true", help="Run pytest smoke contracts (slower)")
    args = parser.parse_args(argv)

    checks: list[tuple[str, Any]] = [
        ("config", check_config),
        ("health", check_health),
        ("model_registry", check_model_registry),
    ]
    if not args.skip_telegram:
        checks.append(("telegram_bot_api", check_telegram_bot_api))
    if not args.skip_worker_sql:
        checks.append(("worker_funnel_sql", check_worker_funnel_sql_smoke))
    if args.with_contract_tests:
        checks.append(("contract_tests", check_contract_tests))

    results: list[CheckResult] = []
    for name, fn in checks:
        if args.as_json:
            with redirect_stdout(sys.stderr):
                results.append(await _run_check(name, fn))
        else:
            results.append(await _run_check(name, fn))

    ok = all(r.ok for r in results)
    payload = {
        "ok": ok,
        "checks": [asdict(r) for r in results],
        "summary": {
            "ok": sum(1 for r in results if r.ok),
            "fail": sum(1 for r in results if not r.ok),
        },
    }

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        _print_human(results)

    return 0 if ok else 1


def main() -> int:
    return asyncio.run(_amain(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
