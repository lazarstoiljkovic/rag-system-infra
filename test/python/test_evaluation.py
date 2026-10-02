"""Testovi za ciste funkcije evaluacije: statistika, metrike pretrage, spajanje zapisa."""

import math
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "evaluation"))
sys.path.insert(0, os.path.join(ROOT, "lambda", "query_handler"))

from dataset import (ALL, HARD, IMAGE_ONLY, TEXT, context_for_judge,  # noqa: E402
                     groups_of, join_records, latest_by_key, load_questions)
from prompting import context_header  # noqa: E402
from retrieval_metrics import (document_recall, first_relevant_rank,  # noqa: E402
                               same_retrieval, summarize)
from stats import (cohen_kappa, mcnemar_chi2, mcnemar_exact, mean,  # noqa: E402
                   paired_counts)


class McNemarTest(unittest.TestCase):
    def test_primer_iz_rada(self):
        # Odeljak 2.5.4: B tacna na 3 pitanja gde A nije, A na 1 gde B nije.
        self.assertAlmostEqual(mcnemar_exact(1, 3), 0.625)

    def test_simetrican(self):
        self.assertEqual(mcnemar_exact(2, 7), mcnemar_exact(7, 2))

    def test_bez_neslaganja(self):
        self.assertEqual(mcnemar_exact(0, 0), 1.0)
        self.assertEqual(mcnemar_chi2(0, 0), (0.0, 1.0))

    def test_jaka_razlika_je_znacajna(self):
        self.assertLess(mcnemar_exact(0, 10), 0.01)

    def test_p_nikad_preko_1(self):
        self.assertEqual(mcnemar_exact(3, 3), 1.0)

    def test_chi2_sa_korekcijom(self):
        stat, p = mcnemar_chi2(2, 10)
        self.assertAlmostEqual(stat, 49 / 12)
        self.assertTrue(0.04 < p < 0.05)

    def test_negativno_odbijeno(self):
        with self.assertRaises(ValueError):
            mcnemar_exact(-1, 2)


class PairedAndKappaTest(unittest.TestCase):
    def test_tabela(self):
        c = paired_counts([True, True, False, False], [True, False, True, False])
        self.assertEqual(c, {"both": 1, "only_a": 1, "only_b": 1, "neither": 1})

    def test_razlicite_duzine(self):
        with self.assertRaises(ValueError):
            paired_counts([True], [True, False])

    def test_kapa_potpuno_slaganje(self):
        self.assertEqual(cohen_kappa([(True, True), (False, False)]), 1.0)

    def test_kapa_kao_slucajno(self):
        pairs = [(True, True), (True, False), (False, True), (False, False)]
        self.assertAlmostEqual(cohen_kappa(pairs), 0.0)

    def test_prosek_preskace_nan(self):
        self.assertEqual(mean([1.0, float("nan"), 0.0]), 0.5)
        self.assertTrue(math.isnan(mean([float("nan")])))


def _ctx(rank, doc, ctype="text", chunk=None):
    return {"rank": rank, "documentId": doc, "chunkType": ctype,
            "chunkId": chunk or "{}#{}".format(doc, rank), "text": "t", "page": 1}


def _rec(contexts, documents=("d1",), image_only=False):
    return {"contexts": contexts, "documents": list(documents), "imageOnly": image_only}


class RetrievalMetricsTest(unittest.TestCase):
    def test_prvi_relevantan(self):
        r = _rec([_ctx(1, "x"), _ctx(2, "d1"), _ctx(3, "d1")])
        self.assertEqual(first_relevant_rank(r), 2)

    def test_samo_na_slici_trazi_sliku(self):
        r = _rec([_ctx(1, "d1"), _ctx(2, "d1", "image")], image_only=True)
        self.assertEqual(first_relevant_rank(r), 2)

    def test_bez_relevantnog(self):
        self.assertIsNone(first_relevant_rank(_rec([_ctx(1, "x")])))

    def test_odziv_dokumenata(self):
        r = _rec([_ctx(1, "d1")], documents=("d1", "d2"))
        self.assertEqual(document_recall(r), 0.5)

    def test_zbirno(self):
        records = [_rec([_ctx(1, "d1")]), _rec([_ctx(1, "x"), _ctx(2, "d1")]), _rec([_ctx(1, "x")])]
        s = summarize(records, k=5)
        self.assertAlmostEqual(s["hit_at_k"], 2 / 3)
        self.assertAlmostEqual(s["mrr"], (1 + 0.5 + 0) / 3)

    def test_rang_preko_k_nije_pogodak(self):
        s = summarize([_rec([_ctx(1, "x"), _ctx(2, "d1")])], k=1)
        self.assertEqual(s["hit_at_k"], 0)
        self.assertEqual(s["mrr"], 0)

    def test_ista_pretraga(self):
        a = _rec([_ctx(1, "d1"), _ctx(2, "d2")])
        b = _rec([_ctx(2, "d2"), _ctx(1, "d1")])   # redosled u zapisu nije bitan, rang jeste
        self.assertTrue(same_retrieval(a, b))
        self.assertFalse(same_retrieval(a, _rec([_ctx(1, "d2"), _ctx(2, "d1")])))


class DatasetTest(unittest.TestCase):
    def test_grupe(self):
        self.assertEqual(groups_of({"samo_na_slici": True, "tesko_za_opis": True}),
                         [ALL, IMAGE_ONLY, HARD])
        self.assertEqual(groups_of({}), [ALL, TEXT])

    def test_skup_pitanja_ucitan(self):
        questions = load_questions()
        self.assertEqual(len(questions), 106)
        for q in questions:
            self.assertTrue(q["odgovor"] and q["dokumenti"])

    def test_poslednji_zapis_vazi(self):
        rows = [{"id": "A1", "variant": "A", "n": 1}, {"id": "A1", "variant": "A", "n": 2}]
        self.assertEqual(latest_by_key(rows, "id", "variant")[("A1", "A")]["n"], 2)

    def test_spajanje_po_query_id(self):
        questions = [{"id": "A1", "pitanje": "p", "odgovor": "o", "dokumenti": ["d1"]}]
        manifest = [{"id": "A1", "variant": "A", "queryId": "q1"},
                    {"id": "A1", "variant": "B", "queryId": "q2", "error": "status 503"}]
        log = [{"queryId": "q1", "contexts": [_ctx(1, "d1")], "attachedImages": [], "answer": "x"}]
        records = {r["variant"]: r for r in join_records(questions, manifest, log)}
        self.assertIsNone(records["A"]["error"])
        self.assertEqual(records["A"]["answer"], "x")
        self.assertEqual(records["B"]["error"], "status 503")

    def test_zapis_koji_fali_u_logu(self):
        questions = [{"id": "A1", "pitanje": "p", "odgovor": "o", "dokumenti": ["d1"]}]
        records = join_records(questions, [{"id": "A1", "variant": "A", "queryId": "nema"}], [])
        self.assertIn("query-log", records[0]["error"])

    def test_kontekst_kao_kod_generatora(self):
        ctx = {"rank": 2, "chunkType": "table", "documentId": "booking-api-v3",
               "page": 1, "text": " | a | b | "}
        text = context_for_judge(ctx, context_header)
        self.assertTrue(text.startswith("[2] (tabela, booking-api-v3, str. 1)\n"))
        self.assertTrue(text.endswith("| a | b |"))


if __name__ == "__main__":
    unittest.main()


class JudgeInputsTest(unittest.TestCase):
    """RAGAS numerise kontekste sam; slike moraju na kraj da "Context n" = [n]."""

    def test_slike_na_kraju_uz_napomenu(self):
        import ragas_eval
        record = {"attachedImages": ["images/a.png"], "contexts": [
            {"rank": 1, "chunkType": "image", "documentId": "d", "page": 1,
             "text": "opis", "imageRef": "images/a.png"},
            {"rank": 2, "chunkType": "text", "documentId": "d", "page": 1, "text": "tekst"},
        ]}
        inputs = ragas_eval.judge_inputs(record, lambda key: "data:image/png;base64,AA==")
        self.assertEqual(inputs["with_images"][:2], inputs["texts"])
        self.assertTrue(inputs["with_images"][0].startswith("[1] "))
        self.assertIn("[1]", inputs["with_images"][2])
        self.assertTrue(inputs["with_images"][3].startswith("data:image/png"))
