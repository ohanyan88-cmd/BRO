"""Production STUDY limits are configuration, and a malformed setting never removes a limit."""
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def surface():
    spec = importlib.util.spec_from_file_location("bro_interact_limits",
                                                  ROOT / "scripts" / "bro_interact.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StudyLimitTests(unittest.TestCase):
    def setUp(self):
        self.surface = surface()
        for name in ("BRO_STUDY_ITEM_BUDGET", "BRO_STUDY_DIMINISHING_AFTER"):
            self.addCleanup(os.environ.pop, name, None)
            os.environ.pop(name, None)

    def test_night_school_defaults(self):
        """A library is wider than a repository, and stops later than one."""
        self.assertEqual(self.surface.study_item_budget(), 30)
        self.assertEqual(self.surface.study_diminishing_after(), 6)

    def test_both_limits_are_configurable(self):
        os.environ["BRO_STUDY_ITEM_BUDGET"] = "12"
        os.environ["BRO_STUDY_DIMINISHING_AFTER"] = "3"
        self.assertEqual(self.surface.study_item_budget(), 12)
        self.assertEqual(self.surface.study_diminishing_after(), 3)

    def test_a_malformed_limit_falls_back_to_the_default(self):
        os.environ["BRO_STUDY_ITEM_BUDGET"] = "many"
        os.environ["BRO_STUDY_DIMINISHING_AFTER"] = ""
        self.assertEqual(self.surface.study_item_budget(), 30)
        self.assertEqual(self.surface.study_diminishing_after(), 6)

    def test_a_limit_below_one_is_raised_not_honoured(self):
        """Zero would mean 'no budget' or 'stop immediately'; neither is a limit."""
        os.environ["BRO_STUDY_ITEM_BUDGET"] = "0"
        os.environ["BRO_STUDY_DIMINISHING_AFTER"] = "-4"
        self.assertEqual(self.surface.study_item_budget(), 1)
        self.assertEqual(self.surface.study_diminishing_after(), 1)


if __name__ == "__main__":
    unittest.main()


class StudyRefreshSwitchTests(unittest.TestCase):
    """Re-reading covered ground reverses a boundary, so an operator states it."""

    def setUp(self):
        self.surface = surface()
        self.addCleanup(os.environ.pop, "BRO_STUDY_REFRESH", None)
        os.environ.pop("BRO_STUDY_REFRESH", None)

    def test_refresh_is_off_by_default(self):
        self.assertFalse(self.surface.study_refresh_requested())

    def test_an_operator_can_turn_it_on(self):
        for value in ("1", "true", "yes", "on"):
            os.environ["BRO_STUDY_REFRESH"] = value
            self.assertTrue(self.surface.study_refresh_requested(), value)

    def test_mission_prose_can_never_turn_it_on(self):
        """The live failure: "do not re-study" contained "re-study" and enabled a refresh,
        which disabled the withholding the same sentence was asking for."""
        import inspect
        # Structural, not textual: the function takes no request at all, so no wording of a
        # mission can reach the decision.
        self.assertEqual(len(inspect.signature(
            self.surface.study_refresh_requested).parameters), 0)
        with self.assertRaises(TypeError):
            self.surface.study_refresh_requested(
                "do not re-study material that is already sufficiently verified")
        self.assertFalse(self.surface.study_refresh_requested())
