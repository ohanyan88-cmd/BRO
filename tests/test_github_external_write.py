import unittest

from bro_runtime.action_runtime import EffectState
from bro_runtime.github_provider import GitHubAcceptanceTarget, GitHubIssueCommentProvider, GitHubProviderRejected


class FakeGitHub:
    def __init__(self): self.comments=[]; self.posts=0
    def __call__(self, method, url, token, payload):
        if method == "GET": return [dict(x) for x in self.comments]
        self.posts += 1
        item={"id": 100 + self.posts, "html_url": "https://github.test/comment", **payload}
        self.comments.append(item); return dict(item)


class GitHubExternalWriteProviderTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeGitHub(); self.provider=GitHubIssueCommentProvider(
            GitHubAcceptanceTarget("safe-owner", "acceptance-repo", 7), transport=self.api)
        self.inputs={"token":"SECRET", "operation":"github.issue_comment.ensure", "owner":"safe-owner",
                     "repository":"acceptance-repo", "issue_number":7, "idempotency_key":"task/action/1", "body":"BRO acceptance"}

    def test_write_reconciles_external_truth_before_dispatch_and_retry_does_not_duplicate(self):
        first=self.provider.invoke(dict(self.inputs)); second=self.provider.invoke(dict(self.inputs))
        self.assertEqual(first.effect_state, EffectState.POSSIBLE)
        self.assertEqual(second.effect_state, EffectState.CONFIRMED)
        self.assertEqual(self.api.posts, 1)
        self.assertNotIn(self.inputs["idempotency_key"], self.api.comments[0]["body"])
        self.assertIn(self.provider.marker_for(self.inputs["idempotency_key"]), self.api.comments[0]["body"])
        read=dict(self.inputs, operation="github.issue_comment.read")
        observation=self.provider.invoke(read)
        self.assertEqual(observation.effect_state, EffectState.NONE)
        self.assertTrue(observation.result["matches_expected"])
        self.assertTrue(observation.observation_refs[0].startswith("github-readback:sha256:"))

    def test_conflicting_replay_and_arbitrary_target_fail_closed(self):
        self.provider.invoke(dict(self.inputs))
        with self.assertRaisesRegex(GitHubProviderRejected, "conflicting replay"):
            self.provider.invoke(dict(self.inputs, body="different"))
        with self.assertRaisesRegex(GitHubProviderRejected, "outside"):
            self.provider.invoke(dict(self.inputs, repository="victim"))
        self.assertEqual(self.api.posts, 1)

    def test_adapter_declares_secret_and_provider_error_never_contains_it(self):
        self.assertEqual(self.provider.adapter().required_secrets, ("token",))
        with self.assertRaises(GitHubProviderRejected) as raised:
            self.provider.invoke(dict(self.inputs, token=""))
        self.assertNotIn("SECRET", str(raised.exception))
