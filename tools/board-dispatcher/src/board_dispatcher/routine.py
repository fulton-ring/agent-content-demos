"""Starts a Research worker session through the Claude Code routine API."""

import json
import urllib.request

FIRE_URL = "https://api.anthropic.com/v1/claude_code/routines/{routine_id}/fire"
TIMEOUT_SECONDS = 30


class RoutineError(RuntimeError):
    pass


def start_worker(routine_id: str, token: str, issue_ref: str) -> str:
    """Fire the worker routine for one issue. Returns the new session's URL."""
    assert routine_id.startswith("trig_"), "routine id must start with trig_"
    assert token, "routine token is empty"
    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        FIRE_URL.format(routine_id=routine_id),
        data=json.dumps({"text": issue_ref}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        if response.status != 200:  # noqa: PLR2004
            raise RoutineError(f"Routine fire returned HTTP {response.status}")
        payload = json.load(response)
    url = payload.get("claude_code_session_url")
    if not url:
        raise RoutineError("Routine fire response has no session URL")
    return url
