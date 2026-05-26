"""Контракты аналитики/наблюдаемости: воронка, telemetry, smoke JSON."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def test_worker_funnel_includes_non_text_generation_events():
    # Event names live in the job handlers (daily_stats/alerts), not in main.py dispatcher
    stats_src = _read("services/worker/jobs/daily_stats.py")
    alerts_src = _read("services/worker/jobs/alerts.py")
    combined = stats_src + alerts_src
    for event_name in ("message_sent", "image_generated", "video_generated", "music_generated"):
        assert event_name in combined, f"В funnel нет события: {event_name}"


def test_handlers_emit_generation_events_for_funnel():
    assert "image_generated" in _read("services/bot/handlers/image.py")
    assert "video_generated" in _read("services/bot/handlers/video.py")
    assert "music_generated" in _read("services/bot/handlers/music.py")


def test_smoke_json_redirects_noise_to_stderr():
    src = _read("scripts/smoke_user_flow.py")
    assert "redirect_stdout" in src
    assert "redirect_stdout(sys.stderr)" in src


def test_video_queue_path_propagates_policy_usage_and_telemetry():
    video_src = _read("services/bot/handlers/video.py")
    worker_src = _read("services/worker/main.py")

    # bot queues enough metadata for deferred refund + policy rollback
    assert '"policy_usage": spend.get("policy_usage")' in video_src
    assert '"trial": bool(spend.get("trial"))' in video_src
    assert '"unlimited": bool(spend.get("unlimited"))' in video_src

    # worker queue path logs success/error and uses refund_spend_credits (in video_generate job)
    video_job_src = _read("services/worker/jobs/video_generate.py")
    assert 'refund_spend_credits' in video_job_src
    assert 'log_ai_success' in video_job_src
    assert 'log_ai_error' in video_job_src
    assert '"source": "queue"' in video_job_src
