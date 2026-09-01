"""Legacy direct-provider acceptance; superseded by the governed workflow harness."""
import hashlib
import json
import os
from pathlib import Path
import unittest

from bro_runtime.github_provider import GitHubAcceptanceTarget, GitHubIssueCommentProvider

REQUIRED=("BRO_GITHUB_TOKEN", "BRO_GITHUB_OWNER", "BRO_GITHUB_REPOSITORY", "BRO_GITHUB_ISSUE")
LIVE_ENABLED = os.environ.get("BRO_GITHUB_ACCEPTANCE") == "1"
LIVE_CONFIGURED = all(os.environ.get(k) for k in REQUIRED)


@unittest.skipUnless(LIVE_ENABLED and LIVE_CONFIGURED, "requires BRO_GITHUB_ACCEPTANCE=1 and " + ", ".join(REQUIRED))
class GitHubAuthenticatedAcceptanceTests(unittest.TestCase):
    def test_authenticated_write_retry_and_independent_readback(self):
        target=GitHubAcceptanceTarget(os.environ["BRO_GITHUB_OWNER"], os.environ["BRO_GITHUB_REPOSITORY"], int(os.environ["BRO_GITHUB_ISSUE"]))
        provider=GitHubIssueCommentProvider(target)
        key=os.environ.get("BRO_GITHUB_IDEMPOTENCY_KEY", "bro-authenticated-write-v1")
        body=os.environ.get("BRO_GITHUB_COMMENT_BODY", "BRO governed authenticated external write acceptance v1")
        base={"token":os.environ["BRO_GITHUB_TOKEN"], "owner":target.owner, "repository":target.repository,
              "issue_number":target.issue_number, "idempotency_key":key, "body":body}
        first=provider.invoke(dict(base, operation="github.issue_comment.ensure"))
        retry=provider.invoke(dict(base, operation="github.issue_comment.ensure"))
        observed=provider.invoke(dict(base, operation="github.issue_comment.read"))
        self.assertTrue(retry.result["matches_expected"])
        self.assertTrue(observed.result["matches_expected"])
        self.assertEqual(first.result["comment_id"], retry.result["comment_id"])
        record={"provider":"github", "resource_ref":target.resource_ref, "comment_id":observed.result["comment_id"],
                "resource_url":observed.result["resource_url"], "idempotency_key_hash":hashlib.sha256(key.encode()).hexdigest(),
                "result_hash":observed.observation_refs[0], "matches_expected":True}
        path=Path(os.environ.get("BRO_GITHUB_ACCEPTANCE_RECORD", "artifacts/github-write-acceptance.json"))
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(record, sort_keys=True, indent=2)+"\n")
