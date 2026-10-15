"""Typed HTTP client for the AgentScore backend (TSK_123).

Thin wrapper around ``httpx`` that:
  • adds the Bearer token from `AGENTSCORE_TOKEN` on every call,
  • never logs, prints, or echoes that token,
  • returns parsed JSON dicts the caller can hand straight to
    `compute_release_decision`.

Each method maps 1:1 to a documented v2 endpoint. Errors raise
:class:`AgentScoreApiError` carrying only a status code + scrubbed
message — never the request headers or response body verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


DEFAULT_API_URL = "https://api.agentscore.tech"
_REDACTED = "<redacted>"


@dataclass
class AgentScoreApiError(Exception):
    """HTTP error from the AgentScore backend.

    The string representation is intentionally short and never includes
    the request Authorization header or response body verbatim — only
    the status + a scrubbed snippet so the CLI can render a clear error
    without leaking secrets.
    """

    status_code: int
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"AgentScore API error {self.status_code}: {self.message}"


def _scrub(text: str) -> str:
    """Redact obvious secret-shaped substrings in a short error snippet."""
    out = text
    for pattern in (
        "Bearer ",
        "Authorization",
        "authorization",
        "sk_live_",
        "pk_live_",
        "pk_test_",
        "whsec_",
        "GOCSPX-",
        "AIzaSy",
    ):
        out = out.replace(pattern, _REDACTED)
    return out[:200]


class AgentScoreClient:
    """Read-only client for the v2 release-gate endpoints.

    Constructed from a (sanitised) ``api_url`` + the bearer token; the
    token is held only in the HTTPX headers dict and never logged. The
    context manager protocol ensures connection cleanup.
    """

    def __init__(
        self,
        *,
        api_url: str = DEFAULT_API_URL,
        token: str,
        timeout: float = 30.0,
    ) -> None:
        if not token:
            raise AgentScoreApiError(
                status_code=0,
                message=(
                    "AGENTSCORE_TOKEN is empty. Set it to an AgentScore API "
                    "key (ags_key_…, Settings → API keys), or pass --token."
                ),
            )
        self._api_url = api_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "agentscore-cli/0.1.0",
            },
        )

    def __enter__(self) -> "AgentScoreClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ #
    # Endpoints                                                           #
    # ------------------------------------------------------------------ #

    def _get_json(self, path: str) -> Any:
        url = f"{self._api_url}{path}"
        try:
            r = self._client.get(url)
        except httpx.HTTPError as exc:
            # Never echo the URL with token-bearing headers; the exception
            # str() can include request line in some httpx versions, so
            # scrub defensively.
            raise AgentScoreApiError(
                status_code=0, message=_scrub(str(exc))
            ) from None
        if not r.is_success:
            # Body of a 4xx may include URLs the user pasted but not
            # secrets (we never send our token into a body). Still scrub.
            raise AgentScoreApiError(
                status_code=r.status_code,
                message=_scrub(r.text or r.reason_phrase or "error"),
            )
        try:
            return r.json()
        except ValueError as exc:
            raise AgentScoreApiError(
                status_code=r.status_code,
                message=f"non-JSON response: {_scrub(str(exc))}",
            ) from None

    def get_suite_dashboard(self, suite_id: str) -> dict[str, Any]:
        return self._get_json(f"/v2/evaluations/suites/{suite_id}/dashboard")

    def get_suite_evidence(self, suite_id: str) -> dict[str, Any]:
        return self._get_json(f"/v2/evaluations/suites/{suite_id}/evidence")

    def get_criterion_registry(self) -> dict[str, Any]:
        return self._get_json("/v2/evaluations/criteria/registry")

    def get_policy_registry(self) -> dict[str, Any]:
        return self._get_json("/v2/evaluations/policies/registry")

    def get_gate_template_registry(self) -> dict[str, Any]:
        return self._get_json("/v2/evaluations/gates/registry")


    # ------------------------------------------------------------------ #
    # TSK_1065 — start a run from CI, then wait for it                    #
    # ------------------------------------------------------------------ #

    def start_run(self, agent_id: str, *, idempotency_key: str) -> dict[str, Any]:
        """POST /v2/evaluations/run-all — the full gate for one bot.

        `idempotency_key` makes a retried CI job reuse its run instead of
        paying for a second one.
        """

        url = f"{self._api_url}/v2/evaluations/run-all"
        try:
            r = self._client.post(
                url, json={"agent_id": agent_id, "idempotency_key": idempotency_key}
            )
        except httpx.HTTPError as exc:
            raise AgentScoreApiError(status_code=0, message=_scrub(str(exc))) from None
        if not r.is_success:
            raise AgentScoreApiError(
                status_code=r.status_code, message=_scrub(r.text or r.reason_phrase or "error")
            )
        return r.json()
