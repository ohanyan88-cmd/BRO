"""Authenticated GitHub issue-comment provider for the first external WRITE slice.

The provider is deliberately acceptance-target-bound.  Its stable marker is the
provider-owned reconciliation identity: before every mutation it reads GitHub
and either returns the already matching comment or fails on conflicting state.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .action_runtime import AdapterResult, EffectState
from .provider_adapters import ProviderAdapter


class GitHubProviderRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubAcceptanceTarget:
    owner: str
    repository: str
    issue_number: int
    api_url: str = "https://api.github.com"

    @property
    def resource_ref(self) -> str:
        return f"github:{self.owner}/{self.repository}:issue:{self.issue_number}"


class GitHubIssueCommentProvider:
    """Ensure/read one marker-bound comment on one immutable configured issue."""

    adapter_id = "github-issue-comment"
    version = "v1"
    marker_prefix = "<!-- bro-external-write:"

    def __init__(self, target: GitHubAcceptanceTarget, *, transport=None) -> None:
        if not target.owner or not target.repository or target.issue_number <= 0:
            raise GitHubProviderRejected("explicit GitHub owner, repository, and positive issue are required")
        self.target = target
        self.transport = transport or self._http

    def adapter(self) -> ProviderAdapter:
        return ProviderAdapter(
            self.adapter_id, "github", self.version,
            ("github.issue_comment.ensure", "github.issue_comment.read"), self.invoke,
            idempotent_operations=("github.issue_comment.ensure",), required_secrets=("token",),
        )

    def invoke(self, inputs: dict) -> AdapterResult:
        token = inputs.pop("token", None)
        if not token:
            raise GitHubProviderRejected("mediated GitHub token is required")
        self._require_target(inputs)
        operation = inputs.get("operation")
        key = str(inputs.get("idempotency_key", "")).strip()
        desired = str(inputs.get("body", ""))
        if not key:
            raise GitHubProviderRejected("canonical idempotency key is required")
        marker = f"{self.marker_prefix}{key} -->"
        matches = [item for item in self._comments(token) if marker in str(item.get("body", ""))]
        if len(matches) > 1:
            raise GitHubProviderRejected("ambiguous external idempotency marker")
        if operation == "github.issue_comment.read":
            state = self._state(matches[0], desired, marker) if matches else self._state(None, desired, marker)
            digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
            return AdapterResult(state, EffectState.NONE, observation_refs=(f"github-readback:sha256:{digest}",))
        if operation != "github.issue_comment.ensure":
            raise GitHubProviderRejected("unsupported GitHub operation")
        if matches:
            state = self._state(matches[0], desired, marker)
            if not state["matches_expected"]:
                raise GitHubProviderRejected("conflicting replay for external idempotency marker")
            return AdapterResult(state, EffectState.CONFIRMED)
        payload = {"body": f"{marker}\n{desired}"}
        created = self.transport("POST", self._comments_url(), token, payload)
        return AdapterResult(self._state(created, desired, marker), EffectState.POSSIBLE)

    def _require_target(self, inputs: dict) -> None:
        actual = (inputs.get("owner"), inputs.get("repository"), inputs.get("issue_number"))
        expected = (self.target.owner, self.target.repository, self.target.issue_number)
        if actual != expected:
            raise GitHubProviderRejected("request is outside the configured GitHub acceptance target")

    def _comments(self, token: str) -> list[dict]:
        result = self.transport("GET", self._comments_url() + "?per_page=100", token, None)
        if not isinstance(result, list):
            raise GitHubProviderRejected("GitHub comments read returned invalid state")
        if len(result) == 100:
            raise GitHubProviderRejected("GitHub readback is ambiguous beyond the bounded comment page")
        return result

    def _comments_url(self) -> str:
        t = self.target
        return f"{t.api_url}/repos/{quote(t.owner)}/{quote(t.repository)}/issues/{t.issue_number}/comments"

    @staticmethod
    def _state(comment, desired: str, marker: str) -> dict:
        if comment is None:
            return {"exists": False, "matches_expected": False, "comment_id": None, "resource_url": None}
        body = str(comment.get("body", ""))
        return {"exists": True, "matches_expected": body == f"{marker}\n{desired}",
                "comment_id": comment.get("id"), "resource_url": comment.get("html_url")}

    @staticmethod
    def _http(method: str, url: str, token: str, payload: dict | None):
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(url, data=data, method=method, headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "BRO-acceptance",
            "Content-Type": "application/json",
        })
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never include response bodies: providers can echo credentials or other sensitive input.
            raise GitHubProviderRejected(f"GitHub API rejected {method} with status {exc.code}") from None
