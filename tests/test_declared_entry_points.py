"""A declared canonical entry point does not depend on a model being reachable.

Live acceptance found this: the curriculum selected networking / net.ip, printed the exact
document to fetch, and then acquired nothing and reported the corpus exhausted. The model
call had raised, and the handler reset the entire proposal list -- discarding the declared
entry points along with the model's. The mission had been told where to go and threw the
address away.
"""
import unittest

from bro_runtime.inference import InferenceRejected
from scripts.bro_interact import proposed_sources

RFC791 = "https://www.rfc-editor.org/rfc/rfc791.html"
GUESS = "https://example.invalid/whatever"


class Refusing:
    def propose_sources(self, subject):
        raise InferenceRejected("the provider refused")


class Silent:
    def propose_sources(self, subject):
        return {}


class Answering:
    def propose_sources(self, subject):
        return {"sources": [{"url": GUESS}]}


class DeclaredEntryPointTests(unittest.TestCase):
    def test_a_refusing_model_does_not_discard_the_declared_document(self):
        proposed, declared = proposed_sources(Refusing(), "continue", (RFC791,))
        self.assertEqual(proposed, [RFC791])
        self.assertEqual(declared, {RFC791})

    def test_a_model_with_nothing_to_say_does_not_discard_it_either(self):
        proposed, _ = proposed_sources(Silent(), "continue", (RFC791,))
        self.assertEqual(proposed, [RFC791])

    def test_an_object_that_is_not_a_model_at_all_does_not_discard_it(self):
        proposed, _ = proposed_sources(object(), "continue", (RFC791,))
        self.assertEqual(proposed, [RFC791])

    def test_the_declared_document_comes_before_the_model_s_guess(self):
        proposed, declared = proposed_sources(Answering(), "continue", (RFC791,))
        self.assertEqual(proposed, [RFC791, GUESS])
        self.assertEqual(declared, {RFC791})
        self.assertNotIn(GUESS, declared)

    def test_without_a_curriculum_the_model_is_still_the_only_answer(self):
        proposed, declared = proposed_sources(Answering(), "continue", ())
        self.assertEqual(proposed, [GUESS])
        self.assertEqual(declared, set())


if __name__ == "__main__":
    unittest.main()
