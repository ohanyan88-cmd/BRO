"""A pasted paragraph is one request, not one mission per line."""
import unittest

from scripts.bro_interact import BLOCK_DELIMITER, read_request


class Reader:
    def __init__(self, lines):
        self.lines = list(lines)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class MultilineRequestTests(unittest.TestCase):
    def test_a_single_line_is_unchanged(self):
        reader = Reader(["Study yourself."])
        self.assertEqual(read_request(reader), "Study yourself.")
        self.assertEqual(reader.prompts, ["You > "])

    def test_a_block_becomes_one_request(self):
        reader = Reader([BLOCK_DELIMITER,
                         "Continue studying yourself.",
                         "Focus on the Introduction to BRO.",
                         "Resolve the uncertainties using authoritative sources only.",
                         BLOCK_DELIMITER,
                         "next"])
        request = read_request(reader)
        self.assertEqual(
            request,
            "Continue studying yourself.\n"
            "Focus on the Introduction to BRO.\n"
            "Resolve the uncertainties using authoritative sources only.",
        )
        self.assertEqual(read_request(reader), "next", "the reader stops at the closing delimiter")

    def test_the_observed_failure_no_longer_splits_a_paragraph(self):
        # The production incident: the trailing clause of a pasted Armenian instruction
        # arrived on its own and became a standalone study mission.
        lines = ["Ուսումնասիրիր հետևյալը՝",
                 "արտաքին տիրույթի աղբյուրները,",
                 "վավերացման կանոնները և բացառությունները։"]
        reader = Reader([BLOCK_DELIMITER, *lines, BLOCK_DELIMITER])
        request = read_request(reader)
        self.assertEqual(request, "\n".join(lines))
        self.assertIn("վավերացման կանոնները և բացառությունները։", request)
        self.assertNotEqual(request, "վավերացման կանոնները և բացառությունները։")

    def test_without_the_block_each_line_is_still_its_own_request(self):
        # Documenting the convention honestly: ordinary interaction is unchanged, which
        # is exactly why a paste needs the delimiter.
        reader = Reader(["first line", "second line"])
        self.assertEqual(read_request(reader), "first line")
        self.assertEqual(read_request(reader), "second line")

    def test_end_of_input_returns_none(self):
        self.assertIsNone(read_request(Reader([])))

    def test_an_unclosed_block_still_returns_what_was_given(self):
        reader = Reader([BLOCK_DELIMITER, "one", "two"])
        self.assertEqual(read_request(reader), "one\ntwo")

    def test_an_empty_block_is_an_empty_request(self):
        self.assertEqual(read_request(Reader([BLOCK_DELIMITER, BLOCK_DELIMITER])), "")

    def test_a_block_keeps_non_english_text_intact(self):
        reader = Reader([BLOCK_DELIMITER, "Ուսումնասիրիր ինքդ քեզ։", "Կենտրոնացիր ճարտարապետության վրա։", BLOCK_DELIMITER])
        self.assertEqual(read_request(reader), "Ուսումնասիրիր ինքդ քեզ։\nԿենտրոնացիր ճարտարապետության վրա։")

    def test_interrupting_a_block_does_not_lose_the_lines_already_given(self):
        class Interrupting(Reader):
            def __call__(self, prompt):
                if len(self.prompts) == 2:
                    self.prompts.append(prompt)
                    raise KeyboardInterrupt
                return super().__call__(prompt)

        reader = Interrupting([BLOCK_DELIMITER, "kept"])
        self.assertEqual(read_request(reader), "kept")


if __name__ == "__main__":
    unittest.main()
