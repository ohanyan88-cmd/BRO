"""Learning in one language and recalling in another, without moving the evidence.

Every case here runs the production path: a real StudySourceReader over a real corpus
directory, GovernedStudyRuntime, DurableLearningMemory, and the same recall() the
conversational surface calls. The model is stubbed because these tests must not reach the
network -- but nothing about the memory or retrieval path is stubbed, which is the part
the claim "BRO can recall across languages" is actually about.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bro_runtime.learning_memory import (
    DurableLearningMemory,
    KnowledgeKind,
    VerificationState,
    detect_language,
)
from bro_runtime.study_runtime import (
    GovernedStudyRuntime,
    StudyContext,
    StudySourceReader,
)

ENGLISH = """# OAuth 2.0 security
Authorization servers MUST support PKCE for all clients.
"""
RUSSIAN = """# Безопасность OAuth 2.0
Серверы авторизации обязаны поддерживать PKCE для всех клиентов.
"""
ARMENIAN = """# Հայերենի ուղղագրություն
Հայերենի ուղղագրության նորմը սահմանում է Լեզվի կոմիտեն։
"""

CLAIMS = {
    "en": {"claim": "Authorization servers must support PKCE for all clients.",
           "evidence_quote": "Authorization servers MUST support PKCE for all clients.",
           "recall_terms": ["լիազորման սերվեր", "PKCE", "серверы авторизации", "authorization server"]},
    "ru": {"claim": "Серверы авторизации обязаны поддерживать PKCE.",
           "evidence_quote": "Серверы авторизации обязаны поддерживать PKCE для всех клиентов.",
           "recall_terms": ["լիազորման սերվեր", "PKCE", "authorization server"]},
    "hy": {"claim": "Հայերենի ուղղագրության նորմը սահմանում է Լեզվի կոմիտեն։",
           "evidence_quote": "Հայերենի ուղղագրության նորմը սահմանում է Լեզվի կոմիտեն։",
           "recall_terms": ["armenian orthography", "language committee", "армянская орфография"]},
}
BY_SOURCE = {"oauth-en.md": "en", "oauth-ru.md": "ru", "orthography-hy.md": "hy"}


class MultilingualLearningTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.corpus = self.home / "corpus"
        self.corpus.mkdir()
        (self.corpus / "oauth-en.md").write_text(ENGLISH, encoding="utf-8")
        (self.corpus / "oauth-ru.md").write_text(RUSSIAN, encoding="utf-8")
        (self.corpus / "orthography-hy.md").write_text(ARMENIAN, encoding="utf-8")
        self.db = self.home / "runtime.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.addCleanup(self.connection.close)
        self.memory = DurableLearningMemory(self.connection)
        self.study()

    # ------------------------------------------------------------------ harness
    def context(self):
        return StudyContext(environment="production", source_revision="a" * 40,
                            instance_id="dbsrv", model_ref="claude-code-cli:sonnet",
                            root_ref=str(self.corpus))

    def planner(self, mission, sources):
        return {"topics": [{"topic": f"study {ref}", "source_ref": ref} for ref in sources]}

    def extractor(self, topic, text):
        for source_ref, language in BY_SOURCE.items():
            if CLAIMS[language]["evidence_quote"] in text:
                return {"claims": [dict(CLAIMS[language], inference=False)]}
        return {"claims": []}

    def runtime(self, memory=None, extractor=None):
        return GovernedStudyRuntime(
            memory or self.memory, StudySourceReader(self.corpus),
            planner=self.planner, extractor=extractor or self.extractor,
            item_budget=10, diminishing_after=6,
        )

    def study(self, memory=None, extractor=None):
        return self.runtime(memory, extractor).study("learn the corpus", self.context())

    def recall(self, question, memory=None):
        return self.runtime(memory).recall(question, self.context())

    def pick(self, question, language, memory=None):
        """The claim learned from a source in `language`, as reached by this question.

        A cross-language question legitimately reaches more than one claim: an Armenian
        question about authorization servers matches both the English and the Russian
        source, because both are about that. Recall is therefore asserted as reachability
        of the right item, not as it being the only answer."""
        found = [item for item in self.recall(question, memory)["knowledge"]
                 if item["source_language"] == language]
        self.assertTrue(found, f"no {language} claim recalled for {question!r}")
        return found[0]

    # ------------------------------------ the four mandatory acceptance cases
    def test_english_source_recalled_by_an_armenian_question(self):
        item = self.pick("Ի՞նչ պետք է աջակցի լիազորման սերվերը", "en")
        self.assertIn("PKCE", item["claim"])
        self.assertEqual(item["verification_state"], VerificationState.VERIFIED.value)
        self.assertEqual(item["evidence_quote"], CLAIMS["en"]["evidence_quote"])
        self.assertEqual(item["evidence_language"], "en")
        self.assertEqual(item["source_language"], "en")

    def test_russian_source_recalled_by_an_armenian_question(self):
        item = self.pick("Ի՞նչ պետք է աջակցի լիազորման սերվերը", "ru")
        self.assertEqual(item["evidence_quote"], CLAIMS["ru"]["evidence_quote"])
        self.assertEqual(item["evidence_language"], "ru")
        self.assertEqual(detect_language(item["evidence_quote"]), "ru")

    def test_armenian_source_recalled_by_an_english_question(self):
        item = self.pick("who sets armenian orthography", "hy")
        self.assertEqual(item["source_language"], "hy")
        self.assertEqual(item["evidence_quote"], CLAIMS["hy"]["evidence_quote"])
        self.assertEqual(item["evidence_language"], "hy")

    def test_same_language_control_still_works(self):
        item = self.pick("what must authorization servers support", "en")
        self.assertEqual(item["source_language"], "en")
        self.assertEqual(item["evidence_quote"], CLAIMS["en"]["evidence_quote"])
        armenian = self.pick("Ո՞վ է սահմանում հայերենի ուղղագրության նորմը", "hy")
        self.assertEqual(armenian["source_language"], "hy")

    # ------------------------------------------------- evidence stays evidence
    def test_a_translated_quote_does_not_become_verified_evidence(self):
        """A quote that is not in the source is not evidence, however true the claim is."""
        translated = {"claims": [{
            "claim": "Authorization servers must support PKCE.",
            "evidence_quote": "Լիազորման սերվերները պարտավոր են աջակցել PKCE-ին։",
            "inference": False,
            "recall_terms": ["PKCE"],
        }]}
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        memory = DurableLearningMemory(connection)
        self.study(memory=memory, extractor=lambda topic, text: translated)
        states = {item.verification_state for item in self.all_items(memory)}
        self.assertNotIn(VerificationState.VERIFIED, states)

    def test_recall_terms_never_become_the_evidence_quote(self):
        """The Armenian and Russian keys that made the claim findable are not in its evidence."""
        item = self.pick("Ի՞նչ պետք է աջակցի լիազորման սերվերը", "en")
        self.assertEqual(item["evidence_quote"], CLAIMS["en"]["evidence_quote"])
        self.assertIn(item["evidence_quote"], ENGLISH)
        for term in ("լիազորման սերվեր", "серверы авторизации"):
            self.assertNotIn(term, item["evidence_quote"])
        self.assertEqual(detect_language(item["evidence_quote"]), "en")

    def test_recall_terms_carry_no_authority(self):
        stored = [item for item in self.all_items(self.memory) if item.source_language == "en"][0]
        self.assertIn("լիազորման սերվեր", stored.recall_terms)
        self.assertIs(stored.kind, KnowledgeKind.VERIFIED_KNOWLEDGE)
        self.assertEqual(stored.evidence_quote, CLAIMS["en"]["evidence_quote"])
        self.assertEqual(stored.confidence,
                         [item for item in self.all_items(self.memory)
                          if item.source_language == "hy"][0].confidence)

    def test_answering_across_languages_does_not_duplicate_the_item(self):
        """One canonical learned item, reachable from three languages -- not three copies."""
        english = [item for item in self.all_items(self.memory) if item.source_language == "en"]
        self.assertEqual(len(english), 1)
        identifiers = {
            self.pick("Ի՞նչ պետք է աջակցի լիազորման սերվերը", "en")["knowledge_id"],
            self.pick("what must authorization servers support", "en")["knowledge_id"],
            self.pick("что обязаны серверы авторизации", "en")["knowledge_id"],
        }
        self.assertEqual(identifiers, {english[0].knowledge_id})

    def test_the_document_language_is_recorded_even_when_the_quote_is_not_in_it(self):
        """An Armenian page quoting an English standard: two languages, both recorded."""
        mixed = self.home / "mixed"
        mixed.mkdir()
        (mixed / "note-hy.md").write_text(
            "Լեզվի կոմիտեն անդրադառնում է չափորոշչին։\n"
            "Standard text: Authorization servers MUST support PKCE.\n"
            "Կոմիտեն դա համարում է պարտադիր։\n", encoding="utf-8")
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        memory = DurableLearningMemory(connection)
        GovernedStudyRuntime(
            memory, StudySourceReader(mixed), planner=self.planner,
            extractor=lambda topic, text: {"claims": [{
                "claim": "The committee treats the PKCE requirement as binding.",
                "evidence_quote": "Authorization servers MUST support PKCE.",
                "inference": False, "recall_terms": ["PKCE"]}]},
            item_budget=4, diminishing_after=2,
        ).study("mixed", self.context())
        item = self.all_items(memory)[0]
        self.assertEqual(item.source_language, "hy", "the document's language was not recorded")
        self.assertEqual(item.evidence_language, "en", "the quote's language was not recorded")
        self.assertEqual(item.evidence_quote, "Authorization servers MUST support PKCE.")

    def test_a_recall_key_can_never_be_as_long_as_a_quote(self):
        """Keys are search terms. A key the length of a sentence is a quote wearing a hat."""
        claim = "Authorization servers must support PKCE for all clients."
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        memory = DurableLearningMemory(connection)
        self.study(memory=memory, extractor=lambda topic, text: {"claims": [{
            "claim": claim,
            "evidence_quote": CLAIMS["en"]["evidence_quote"],
            "inference": False,
            "recall_terms": [claim, "x" * 200, "PKCE", "a"],
        }]} if CLAIMS["en"]["evidence_quote"] in text else {"claims": []})
        stored = self.all_items(memory)[0]
        self.assertEqual(stored.recall_terms, ("pkce",))
        self.assertNotIn(claim.lower(), stored.recall_terms)

    # ------------------------------------------------------------ persistence
    def test_source_language_and_cross_language_recall_survive_a_restart(self):
        self.connection.close()
        reopened = sqlite3.connect(self.db)
        self.addCleanup(reopened.close)
        memory = DurableLearningMemory(reopened)
        item = self.pick("Ի՞նչ պետք է աջակցի լիազորման սերվերը", "en", memory)
        self.assertEqual(item["evidence_quote"], CLAIMS["en"]["evidence_quote"])
        russian = self.pick("Ի՞նչ պետք է աջակցի լիազորման սերվերը", "ru", memory)
        self.assertEqual(russian["evidence_quote"], CLAIMS["ru"]["evidence_quote"])
        armenian = self.pick("who sets armenian orthography", "hy", memory)
        self.assertEqual(armenian["source_language"], "hy")
        self.assertEqual(armenian["evidence_quote"], CLAIMS["hy"]["evidence_quote"])

    def test_armenian_unicode_survives_ingestion_storage_and_verification(self):
        stored = [item for item in self.all_items(self.memory) if item.source_language == "hy"][0]
        self.assertEqual(stored.evidence_quote, CLAIMS["hy"]["evidence_quote"])
        self.assertIn(stored.evidence_quote, ARMENIAN)
        self.assertIs(stored.kind, KnowledgeKind.VERIFIED_KNOWLEDGE)
        self.connection.close()
        reopened = sqlite3.connect(self.db)
        self.addCleanup(reopened.close)
        again = [item for item in self.all_items(DurableLearningMemory(reopened))
                 if item.source_language == "hy"][0]
        self.assertEqual(again.evidence_quote, CLAIMS["hy"]["evidence_quote"])
        self.assertEqual(again.evidence_quote.encode("utf-8"),
                         CLAIMS["hy"]["evidence_quote"].encode("utf-8"))

    def all_items(self, memory):
        rows = memory.connection.execute(
            "SELECT DISTINCT mission_id FROM bro_study_knowledge").fetchall()
        return [item for row in rows for item in memory.knowledge(row[0])]


if __name__ == "__main__":
    unittest.main()
