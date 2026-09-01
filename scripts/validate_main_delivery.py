#!/usr/bin/env python3
"""Fail closed when a main-branch push is not associated with a merged PR."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def associated_pull_requests(repository: str, sha: str, token: str) -> list[dict]:
    url=f"https://api.github.com/repos/{repository}/commits/{sha}/pulls"
    request=urllib.request.Request(
        url,
        headers={
            "Accept":"application/vnd.github+json",
            "Authorization":f"Bearer {token}",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"BRO-main-delivery-guard",
        },
    )
    with urllib.request.urlopen(request,timeout=15) as response:
        body=json.loads(response.read().decode("utf-8"))
    if not isinstance(body,list):
        raise RuntimeError("GitHub associated-PR response is not a list")
    return body


def validate(*, event_name: str, ref: str, repository: str, sha: str, token: str, pulls: list[dict] | None=None) -> None:
    if event_name != "push" or ref != "refs/heads/main":
        return
    if not repository or not sha:
        raise RuntimeError("main delivery guard requires repository and commit sha")
    if pulls is None:
        if not token:
            raise RuntimeError("main delivery guard requires GITHUB_TOKEN")
        pulls=associated_pull_requests(repository,sha,token)
    merged=[pr for pr in pulls if pr.get("merged_at") and pr.get("base",{}).get("ref")=="main"]
    if not merged:
        raise RuntimeError("DIRECT MAIN PUSH REJECTED: deliver changes through branch -> PR -> green CI -> merge")


def main() -> int:
    try:
        validate(
            event_name=os.getenv("GITHUB_EVENT_NAME",""),
            ref=os.getenv("GITHUB_REF",""),
            repository=os.getenv("GITHUB_REPOSITORY",""),
            sha=os.getenv("GITHUB_SHA",""),
            token=os.getenv("GITHUB_TOKEN",""),
        )
    except (RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}",file=sys.stderr)
        return 1
    print("PASS: main delivery is PR-associated or guard is not applicable")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
