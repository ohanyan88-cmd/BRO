import unittest

from scripts.validate_main_delivery import validate


class MainDeliveryGuardTests(unittest.TestCase):
    def test_direct_main_push_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,"DIRECT MAIN PUSH REJECTED"):
            validate(event_name="push",ref="refs/heads/main",repository="ohanyan88-cmd/BRO",sha="abc",token="",pulls=[])

    def test_pr_merged_to_main_is_accepted(self):
        validate(
            event_name="push",
            ref="refs/heads/main",
            repository="ohanyan88-cmd/BRO",
            sha="abc",
            token="",
            pulls=[{"merged_at":"2026-09-01T00:00:00Z","base":{"ref":"main"}}],
        )

    def test_non_main_or_non_push_is_not_blocked(self):
        validate(event_name="pull_request",ref="refs/pull/1/merge",repository="",sha="",token="",pulls=[])
        validate(event_name="push",ref="refs/heads/feature",repository="",sha="",token="",pulls=[])


if __name__=="__main__": unittest.main()
