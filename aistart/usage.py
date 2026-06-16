from __future__ import annotations

import json
import platform
import select
import sqlite3
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .agents import AgentRuntime
from .config import AppConfig


UNKNOWN = "unknown"

# Live Claude Code rate limits are not cached to disk; they are only returned as
# `anthropic-ratelimit-unified-*` response headers (the same data Claude Code
# `/status` shows). We read them with a minimal probe request using the Claude
# Code OAuth token.
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_PROBE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"
CLAUDE_RATE_LIMIT_HEADER_PREFIX = "anthropic-ratelimit-unified"


@dataclass
class UsageStats:
    agent: str
    session_usage: str = UNKNOWN
    remaining_usage: str = UNKNOWN
    reset_time: str = UNKNOWN
    monthly_limit: str = UNKNOWN
    limit_5h: str = UNKNOWN
    reset_5h: str = UNKNOWN
    limit_weekly: str = UNKNOWN
    reset_weekly: str = UNKNOWN
    percent_5h: float | None = None
    percent_weekly: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "session_usage": self.session_usage,
            "remaining_usage": self.remaining_usage,
            "reset_time": self.reset_time,
            "monthly_limit": self.monthly_limit,
            "limit_5h": self.limit_5h,
            "reset_5h": self.reset_5h,
            "limit_weekly": self.limit_weekly,
            "reset_weekly": self.reset_weekly,
            "percent_5h": self.percent_5h,
            "percent_weekly": self.percent_weekly,
            "details": self.details,
            "error": self.error,
        }


def collect_all_usage(
    runtimes: dict[str, AgentRuntime],
    config: AppConfig,
    today: date | None = None,
) -> dict[str, UsageStats]:
    return {
        name: collect_usage(runtime, config, today=today)
        for name, runtime in runtimes.items()
    }


def collect_usage(
    runtime: AgentRuntime,
    config: AppConfig,
    today: date | None = None,
) -> UsageStats:
    agent_config = config.agents.get(runtime.definition.name)
    if agent_config and agent_config.usage_command:
        return _usage_from_helper(runtime.definition.name, agent_config.usage_command)
    if runtime.definition.name == "claude":
        return claude_usage(today=today)
    if runtime.definition.name == "codex":
        return codex_usage(today=today)
    return UsageStats(runtime.definition.name, details={"installed": runtime.installed})


def _usage_from_helper(agent: str, command: list[str]) -> UsageStats:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except OSError as exc:
        return UsageStats(agent, error=str(exc))
    except subprocess.TimeoutExpired:
        return UsageStats(agent, error="usage command timed out")

    if result.returncode != 0:
        return UsageStats(agent, error=result.stderr.strip() or "usage command failed")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return UsageStats(agent, session_usage=result.stdout.strip() or UNKNOWN)
    stats = UsageStats(
        agent,
        session_usage=str(data.get("session_usage", UNKNOWN)),
        remaining_usage=str(data.get("remaining_usage", UNKNOWN)),
        reset_time=str(data.get("reset_time", UNKNOWN)),
        monthly_limit=str(data.get("monthly_limit", UNKNOWN)),
        limit_5h=str(data.get("limit_5h", UNKNOWN)),
        reset_5h=str(data.get("reset_5h", UNKNOWN)),
        limit_weekly=str(data.get("limit_weekly", UNKNOWN)),
        reset_weekly=str(data.get("reset_weekly", UNKNOWN)),
        details=dict(data.get("details", {})),
    )
    _apply_rate_limit_fields(stats, _extract_helper_rate_limit_windows(data))
    return stats


def claude_usage(
    path: Path | None = None,
    today: date | None = None,
    include_rate_limits: bool = True,
    claude_home: Path | None = None,
) -> UsageStats:
    stats_path = path or Path.home() / ".claude" / "stats-cache.json"
    current = today or date.today()
    if not stats_path.exists():
        return UsageStats("claude", error=f"not found: {stats_path}")
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return UsageStats("claude", error=str(exc))

    month_prefix = current.strftime("%Y-%m")
    month_messages = 0
    month_sessions = 0
    month_tools = 0
    for entry in data.get("dailyActivity", []):
        if str(entry.get("date", "")).startswith(month_prefix):
            month_messages += int(entry.get("messageCount", 0) or 0)
            month_sessions += int(entry.get("sessionCount", 0) or 0)
            month_tools += int(entry.get("toolCallCount", 0) or 0)

    month_tokens = 0
    for value in data.values():
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, dict):
                continue
            if not str(entry.get("date", "")).startswith(month_prefix):
                continue
            tokens_by_model = entry.get("tokensByModel")
            if isinstance(tokens_by_model, dict):
                month_tokens += sum(int(v or 0) for v in tokens_by_model.values())

    if month_tokens:
        summary = f"{month_tokens:,} tokens, {month_messages:,} messages this month"
    else:
        summary = f"{month_messages:,} messages, {month_sessions:,} sessions this month"
    details = {
        "month": month_prefix,
        "month_tokens": month_tokens,
        "month_messages": month_messages,
        "month_sessions": month_sessions,
        "month_tool_calls": month_tools,
        "total_sessions": data.get("totalSessions"),
        "total_messages": data.get("totalMessages"),
        "last_computed_date": data.get("lastComputedDate"),
    }
    rate_limits = claude_rate_limits(claude_home) if include_rate_limits else None
    if rate_limits:
        details["rate_limits"] = rate_limits

    window_5h = rate_limits.get("5h") if rate_limits else None
    window_weekly = rate_limits.get("weekly") if rate_limits else None
    return UsageStats(
        "claude",
        session_usage=summary,
        limit_5h=_format_window_usage(window_5h),
        reset_5h=_format_window_reset(window_5h),
        limit_weekly=_format_window_usage(window_weekly),
        reset_weekly=_format_window_reset(window_weekly),
        percent_5h=_window_percent(window_5h),
        percent_weekly=_window_percent(window_weekly),
        details=details,
    )


def codex_usage(
    path: Path | None = None,
    today: date | None = None,
    include_rate_limits: bool = True,
) -> UsageStats:
    db_path = path or Path.home() / ".codex" / "state_5.sqlite"
    current = today or date.today()
    if not db_path.exists():
        return UsageStats("codex", error=f"not found: {db_path}")

    month_start = datetime(current.year, current.month, 1)
    if current.month == 12:
        month_end = datetime(current.year + 1, 1, 1)
    else:
        month_end = datetime(current.year, current.month + 1, 1)
    start_ms = int(month_start.timestamp() * 1000)
    end_ms = int(month_end.timestamp() * 1000)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            month_count, month_tokens = conn.execute(
                """
                select count(*), coalesce(sum(tokens_used), 0)
                from threads
                where coalesce(updated_at_ms, updated_at * 1000) >= ?
                  and coalesce(updated_at_ms, updated_at * 1000) < ?
                """,
                (start_ms, end_ms),
            ).fetchone()
            total_count, total_tokens = conn.execute(
                "select count(*), coalesce(sum(tokens_used), 0) from threads"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return UsageStats("codex", error=str(exc))

    details = {
        "month": current.strftime("%Y-%m"),
        "month_tokens": int(month_tokens),
        "month_sessions": int(month_count),
        "total_tokens": int(total_tokens),
        "total_sessions": int(total_count),
    }
    rate_limits = codex_rate_limits() if include_rate_limits else None
    if rate_limits:
        details["rate_limits"] = rate_limits

    window_5h = rate_limits.get("5h") if rate_limits else None
    window_weekly = rate_limits.get("weekly") if rate_limits else None
    return UsageStats(
        "codex",
        session_usage=f"{int(month_tokens):,} tokens, {int(month_count):,} sessions this month",
        limit_5h=_format_window_usage(window_5h),
        reset_5h=_format_window_reset(window_5h),
        limit_weekly=_format_window_usage(window_weekly),
        reset_weekly=_format_window_reset(window_weekly),
        percent_5h=_window_percent(window_5h),
        percent_weekly=_window_percent(window_weekly),
        details=details,
    )


def codex_rate_limits(timeout: float = 5.0) -> dict[str, dict[str, Any]] | None:
    response = _read_codex_rate_limits_from_app_server(timeout=timeout)
    if not response:
        return None
    return _extract_codex_rate_limit_windows(response)


def claude_rate_limits(
    claude_home: Path | None = None,
    timeout: float = 8.0,
) -> dict[str, dict[str, Any]] | None:
    """Return the live 5h and weekly rate-limit windows for Claude Code.

    The current usage and reset times are only exposed as response headers from
    the Anthropic API, so we issue a minimal probe request authenticated with
    the Claude Code OAuth token. When no live data is available (no token,
    offline, or an explicit sandboxed ``claude_home``) we fall back to scanning
    any cached policy-limit JSON.
    """
    home = claude_home or Path.home() / ".claude"
    # Only read the system keychain for the real default home; an explicit
    # claude_home is treated as a sandbox and limited to files within it.
    token = _claude_oauth_token(home, allow_keychain=claude_home is None)
    if token:
        headers = _read_claude_rate_limit_headers(token, timeout=timeout)
        if headers:
            windows = _windows_from_claude_headers(headers)
            if windows:
                return windows
    return _claude_rate_limits_from_files(home)


def _claude_oauth_token(claude_home: Path, allow_keychain: bool) -> str | None:
    if allow_keychain and platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", CLAUDE_KEYCHAIN_SERVICE, "-w"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except OSError:
            result = None
        if result is not None and result.returncode == 0:
            token = _token_from_credentials_json(result.stdout)
            if token:
                return token
    return _token_from_credentials_json(_read_text(claude_home / ".credentials.json"))


def _token_from_credentials_json(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    expires_at = oauth.get("expiresAt")
    if isinstance(expires_at, (int, float)) and expires_at / 1000 < datetime.now().timestamp():
        return None
    token = oauth.get("accessToken")
    return token if isinstance(token, str) and token else None


def _read_claude_rate_limit_headers(token: str, timeout: float) -> dict[str, str] | None:
    body = json.dumps(
        {
            "model": CLAUDE_PROBE_MODEL,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "."}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        CLAUDE_API_URL,
        data=body,
        headers={
            "authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "oauth-2025-04-20",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return _claude_rate_limit_headers(response.headers)
    except urllib.error.HTTPError as exc:
        # Rate-limit headers are still present on 429/4xx responses.
        return _claude_rate_limit_headers(exc.headers) or None
    except (urllib.error.URLError, OSError):
        return None


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Some Python builds (notably the python.org macOS framework) ship without a
    # populated trust store; fall back to certifi's CA bundle when present.
    if context.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            import certifi

            context.load_verify_locations(certifi.where())
        except Exception:
            pass
    return context


def _claude_rate_limit_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    return {
        str(key).lower(): value
        for key, value in headers.items()
        if str(key).lower().startswith(CLAUDE_RATE_LIMIT_HEADER_PREFIX)
    }


def _windows_from_claude_headers(headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    raw = {
        "5h": _claude_header_window(headers, "5h"),
        "weekly": _claude_header_window(headers, "7d"),
    }
    windows = _extract_generic_rate_limit_windows(raw)
    if not windows:
        return {}
    status = headers.get(f"{CLAUDE_RATE_LIMIT_HEADER_PREFIX}-status")
    if status is not None:
        windows["source"] = {"status": status}
    return windows


def _claude_header_window(headers: dict[str, str], window: str) -> dict[str, Any] | None:
    utilization = headers.get(f"{CLAUDE_RATE_LIMIT_HEADER_PREFIX}-{window}-utilization")
    resets_at = headers.get(f"{CLAUDE_RATE_LIMIT_HEADER_PREFIX}-{window}-reset")
    if utilization is None and resets_at is None:
        return None
    parsed: dict[str, Any] = {}
    if utilization is not None:
        try:
            parsed["utilization"] = float(utilization)
        except ValueError:
            pass
    if resets_at is not None:
        try:
            parsed["resets_at"] = int(resets_at)
        except ValueError:
            pass
    return parsed or None


def _claude_rate_limits_from_files(home: Path) -> dict[str, dict[str, Any]] | None:
    candidates = [
        home / "policy-limits.json",
        home / "policy_limits.json",
        home / "policy-limits-cache.json",
        home / "policy_limits_cache.json",
        home / "cache" / "policy-limits.json",
        home / "cache" / "policy_limits.json",
        home / "cache" / "policy_limits_cache.json",
    ]
    search_dirs = [home, home / "cache", home / "sessions"]
    for directory in search_dirs:
        if not directory.exists():
            continue
        candidates.extend(path for path in directory.glob("*.json") if path not in candidates)

    for candidate in candidates:
        data = _read_json(candidate)
        if not isinstance(data, dict):
            continue
        windows = _extract_claude_rate_limit_windows(data)
        if windows:
            return windows
    return None


def _read_codex_rate_limits_from_app_server(timeout: float) -> dict[str, Any] | None:
    try:
        proc = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except OSError:
        return None

    try:
        requests = [
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "aistart", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            },
            {"id": 2, "method": "account/rateLimits/read", "params": None},
        ]
        assert proc.stdin is not None
        for request in requests:
            proc.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            proc.stdin.flush()

        assert proc.stdout is not None
        deadline = datetime.now().timestamp() + timeout
        while datetime.now().timestamp() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 2 and isinstance(message.get("result"), dict):
                return message["result"]
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=1)
        except Exception:
            proc.kill()
    return None


def _extract_codex_rate_limit_windows(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshot = None
    by_limit_id = response.get("rateLimitsByLimitId")
    if isinstance(by_limit_id, dict):
        snapshot = by_limit_id.get("codex")
        if snapshot is None and by_limit_id:
            snapshot = next(iter(by_limit_id.values()))
    if snapshot is None:
        snapshot = response.get("rateLimits")
    if not isinstance(snapshot, dict):
        return {}

    windows = {}
    primary = _normalize_rate_limit_window(snapshot.get("primary"))
    secondary = _normalize_rate_limit_window(snapshot.get("secondary"))
    if primary:
        windows["5h"] = primary
    if secondary:
        windows["weekly"] = secondary
    windows["source"] = {
        "limit_id": snapshot.get("limitId"),
        "plan_type": snapshot.get("planType"),
        "rate_limit_reached_type": snapshot.get("rateLimitReachedType"),
    }
    return windows


def _extract_helper_rate_limit_windows(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    details = data.get("details")
    if isinstance(details, dict):
        rate_limits = details.get("rate_limits")
        if isinstance(rate_limits, dict):
            windows = _extract_generic_rate_limit_windows(rate_limits)
            if windows:
                return windows

    rate_limits = data.get("rate_limits")
    if isinstance(rate_limits, dict):
        windows = _extract_generic_rate_limit_windows(rate_limits)
        if windows:
            return windows
    return {}


def _extract_claude_rate_limit_windows(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    for candidate in _iter_rate_limit_candidates(response):
        windows = _extract_generic_rate_limit_windows(candidate)
        if windows:
            source = {}
            subscription_type = response.get("subscription_type") or response.get("subscriptionType")
            if subscription_type is not None:
                source["subscription_type"] = subscription_type
            rate_limits_available = response.get("rate_limits_available")
            if rate_limits_available is not None:
                source["rate_limits_available"] = rate_limits_available
            if source:
                windows["source"] = source
            return windows
    return {}


def _iter_rate_limit_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    rate_limits = data.get("rate_limits")
    if isinstance(rate_limits, dict):
        candidates.append(rate_limits)
    details = data.get("details")
    if isinstance(details, dict) and isinstance(details.get("rate_limits"), dict):
        candidates.append(details["rate_limits"])
    if "five_hour" in data or "seven_day" in data or "5h" in data or "weekly" in data:
        candidates.append(data)
    for key in ("usage", "limits", "policy_limits", "restrictions", "status"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.extend(_iter_rate_limit_candidates(value))
    return candidates


def _extract_generic_rate_limit_windows(rate_limits: dict[str, Any]) -> dict[str, dict[str, Any]]:
    windows = {}
    five_hour = _normalize_rate_limit_window(
        rate_limits.get("five_hour") or rate_limits.get("5h")
    )
    weekly = _normalize_rate_limit_window(
        rate_limits.get("seven_day") or rate_limits.get("weekly")
    )
    if five_hour:
        windows["5h"] = five_hour
    if weekly:
        windows["weekly"] = weekly
    return windows


def _normalize_rate_limit_window(window: Any) -> dict[str, Any] | None:
    if not isinstance(window, dict):
        return None
    used_percent = (
        window.get("usedPercent")
        if window.get("usedPercent") is not None
        else window.get("used_percentage")
    )
    if used_percent is None and window.get("utilization") is not None:
        try:
            used_percent = float(window["utilization"]) * 100
        except (TypeError, ValueError):
            pass
    normalized = {
        "used_percent": used_percent,
        "window_duration_minutes": (
            window.get("windowDurationMins")
            if window.get("windowDurationMins") is not None
            else window.get("window_duration_minutes")
        ),
        "resets_at": (
            window.get("resetsAt")
            if window.get("resetsAt") is not None
            else window.get("resets_at")
        ),
    }
    if window.get("remainingPercent") is not None:
        normalized["remaining_percent"] = window.get("remainingPercent")
    if window.get("used") is not None:
        normalized["used"] = window.get("used")
    if window.get("limit") is not None:
        normalized["limit"] = window.get("limit")
    return normalized


def _apply_rate_limit_fields(
    stats: UsageStats,
    rate_limits: dict[str, dict[str, Any]] | None,
) -> None:
    if not rate_limits:
        return
    stats.limit_5h = _format_window_usage(rate_limits.get("5h"))
    stats.reset_5h = _format_window_reset(rate_limits.get("5h"))
    stats.limit_weekly = _format_window_usage(rate_limits.get("weekly"))
    stats.reset_weekly = _format_window_reset(rate_limits.get("weekly"))
    stats.percent_5h = _window_percent(rate_limits.get("5h"))
    stats.percent_weekly = _window_percent(rate_limits.get("weekly"))
    stats.details.setdefault("rate_limits", rate_limits)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _format_window_usage(window: dict[str, Any] | None) -> str:
    if not window:
        return UNKNOWN
    if window.get("used") is not None and window.get("limit") is not None:
        return f"{window['used']} / {window['limit']}"
    if window.get("used_percent") is not None:
        return f"{int(window['used_percent'])}% used"
    if window.get("remaining_percent") is not None:
        return f"{int(window['remaining_percent'])}% remaining"
    return UNKNOWN


def _window_percent(window: dict[str, Any] | None) -> float | None:
    """Return the used percentage (0-100) for a window, if it can be derived."""
    if not window:
        return None
    if window.get("used_percent") is not None:
        try:
            return float(window["used_percent"])
        except (TypeError, ValueError):
            return None
    used, limit = window.get("used"), window.get("limit")
    if used is not None and limit is not None:
        try:
            limit_value = float(limit)
            if limit_value > 0:
                return float(used) / limit_value * 100
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    if window.get("remaining_percent") is not None:
        try:
            return 100.0 - float(window["remaining_percent"])
        except (TypeError, ValueError):
            return None
    return None


def format_usage_bar(percent: float | None, fallback: str = UNKNOWN, width: int = 10) -> str:
    """Render a used-percentage as a text bar, e.g. ``████░░░░░░ 40%``.

    Falls back to ``fallback`` when no percentage is available so callers can
    still show non-percentage usage strings (e.g. ``used / limit``).
    """
    if percent is None:
        return fallback
    clamped = max(0.0, min(100.0, float(percent)))
    filled = int(round(clamped / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {int(round(clamped))}%"


def _format_window_reset(window: dict[str, Any] | None) -> str:
    if not window or window.get("resets_at") is None:
        return UNKNOWN
    try:
        return datetime.fromtimestamp(int(window["resets_at"])).strftime("%b %d %H:%M")
    except (TypeError, ValueError, OSError):
        return UNKNOWN
