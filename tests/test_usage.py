import sqlite3
import json
from datetime import date

from aistart.usage import (
    _claude_oauth_token,
    _extract_claude_rate_limit_windows,
    _extract_codex_rate_limit_windows,
    _usage_from_helper,
    _windows_from_claude_headers,
    claude_rate_limits,
    claude_usage,
    codex_usage,
    format_usage_bar,
)


def test_claude_usage_reads_monthly_activity(tmp_path):
    stats = tmp_path / "stats-cache.json"
    stats.write_text(
        json.dumps(
            {
                "lastComputedDate": "2026-06-12",
                "dailyActivity": [
                    {"date": "2026-06-01", "messageCount": 3, "sessionCount": 1, "toolCallCount": 2},
                    {"date": "2026-05-31", "messageCount": 9, "sessionCount": 9, "toolCallCount": 9},
                ],
                "dailyTokens": [
                    {"date": "2026-06-01", "tokensByModel": {"claude": 100}},
                    {"date": "2026-05-31", "tokensByModel": {"claude": 900}},
                ],
                "totalSessions": 10,
                "totalMessages": 50,
            }
        )
    )

    usage = claude_usage(stats, today=date(2026, 6, 12), include_rate_limits=False)

    assert usage.details["month_messages"] == 3
    assert usage.details["month_sessions"] == 1
    assert usage.details["month_tokens"] == 100
    assert "100 tokens" in usage.session_usage


def test_claude_rate_limits_reads_claude_policy_cache(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "policy_limits.json").write_text(
        json.dumps(
            {
                "subscription_type": "max",
                "rate_limits_available": True,
                "rate_limits": {
                    "five_hour": {"used_percentage": 25.4, "resets_at": 1781307799},
                    "seven_day": {"used_percentage": 70, "resets_at": 1781894599},
                },
            }
        )
    )

    limits = claude_rate_limits(tmp_path)

    assert limits is not None
    assert limits["5h"]["used_percent"] == 25.4
    assert limits["weekly"]["used_percent"] == 70
    assert limits["source"]["subscription_type"] == "max"


def test_format_usage_bar_renders_proportional_bar():
    assert format_usage_bar(40, width=10) == "████░░░░░░ 40%"
    assert format_usage_bar(0, width=10) == "░░░░░░░░░░ 0%"
    assert format_usage_bar(100, width=10) == "██████████ 100%"


def test_format_usage_bar_clamps_and_falls_back():
    assert format_usage_bar(150, width=10) == "██████████ 100%"
    assert format_usage_bar(None, fallback="10 / 100") == "10 / 100"
    assert format_usage_bar(None) == "unknown"


def test_claude_usage_sets_percent_fields(tmp_path):
    stats = tmp_path / "stats-cache.json"
    stats.write_text(json.dumps({"dailyActivity": []}))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "policy_limits.json").write_text(
        json.dumps(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 25.4, "resets_at": 1781307799},
                    "seven_day": {"used_percentage": 70, "resets_at": 1781894599},
                }
            }
        )
    )

    usage = claude_usage(stats, today=date(2026, 6, 12), claude_home=tmp_path)

    assert usage.percent_5h == 25.4
    assert usage.percent_weekly == 70


def test_windows_from_claude_headers_parses_unified_headers():
    headers = {
        "anthropic-ratelimit-unified-status": "allowed",
        "anthropic-ratelimit-unified-5h-utilization": "0.04",
        "anthropic-ratelimit-unified-5h-reset": "1781557200",
        "anthropic-ratelimit-unified-7d-utilization": "0.07",
        "anthropic-ratelimit-unified-7d-reset": "1781906400",
    }

    windows = _windows_from_claude_headers(headers)

    assert windows["5h"]["used_percent"] == 4.0
    assert windows["5h"]["resets_at"] == 1781557200
    assert windows["weekly"]["used_percent"] == 7.000000000000001
    assert windows["weekly"]["resets_at"] == 1781906400
    assert windows["source"]["status"] == "allowed"


def test_windows_from_claude_headers_without_windows_is_empty():
    assert _windows_from_claude_headers({"anthropic-ratelimit-unified-status": "allowed"}) == {}


def test_claude_oauth_token_reads_credentials_file(tmp_path):
    (tmp_path / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "tok-123", "expiresAt": 99999999999999}}),
        encoding="utf-8",
    )

    assert _claude_oauth_token(tmp_path, allow_keychain=False) == "tok-123"


def test_claude_oauth_token_rejects_expired(tmp_path):
    (tmp_path / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "tok-123", "expiresAt": 1}}),
        encoding="utf-8",
    )

    assert _claude_oauth_token(tmp_path, allow_keychain=False) is None


def test_extract_claude_rate_limit_windows_accepts_status_shape():
    response = {
        "rate_limits": {
            "five_hour": {"utilization": 0.312, "resets_at": 1781307799},
            "seven_day": {"utilization": 0.82, "resets_at": 1781894599},
        }
    }

    windows = _extract_claude_rate_limit_windows(response)

    assert windows["5h"]["used_percent"] == 31.2
    assert windows["weekly"]["used_percent"] == 82.0


def test_usage_helper_accepts_nested_rate_limits(tmp_path):
    helper = tmp_path / "usage-helper.py"
    helper.write_text(
        "import json\n"
        "print(json.dumps({"
        "'session_usage':'10 messages this month',"
        "'rate_limits':{"
        "'five_hour':{'used_percentage':50,'resets_at':1781307799},"
        "'seven_day':{'used_percentage':10,'resets_at':1781894599}"
        "}}))\n",
        encoding="utf-8",
    )

    usage = _usage_from_helper("claude", ["python3", str(helper)])

    assert usage.limit_5h == "50% used"
    assert usage.limit_weekly == "10% used"


def test_codex_usage_reads_threads(tmp_path):
    db = tmp_path / "state_5.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        "create table threads (id text, updated_at integer, updated_at_ms integer, tokens_used integer)"
    )
    conn.execute("insert into threads values ('a', 1780704000, 1780704000000, 10)")
    conn.execute("insert into threads values ('b', 1779840000, 1779840000000, 90)")
    conn.commit()
    conn.close()

    usage = codex_usage(db, today=date(2026, 6, 12), include_rate_limits=False)

    assert usage.details["month_tokens"] == 10
    assert usage.details["month_sessions"] == 1
    assert usage.details["total_tokens"] == 100


def test_extract_codex_rate_limit_windows_from_app_server_response():
    response = {
        "rateLimitsByLimitId": {
            "codex": {
                "limitId": "codex",
                "primary": {
                    "usedPercent": 34,
                    "windowDurationMins": 300,
                    "resetsAt": 1781307799,
                },
                "secondary": {
                    "usedPercent": 5,
                    "windowDurationMins": 10080,
                    "resetsAt": 1781894599,
                },
                "planType": "plus",
            }
        }
    }

    windows = _extract_codex_rate_limit_windows(response)

    assert windows["5h"]["used_percent"] == 34
    assert windows["5h"]["window_duration_minutes"] == 300
    assert windows["weekly"]["used_percent"] == 5
    assert windows["weekly"]["window_duration_minutes"] == 10080
    assert windows["source"]["plan_type"] == "plus"
