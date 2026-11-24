"""Testovi za hibridni upit, search pipeline-e i njihovo medjusobno slaganje."""

import os
import sys
import unittest

_LAMBDA = os.path.join(os.path.dirname(__file__), "..", "..", "lambda")
sys.path.insert(0, os.path.join(_LAMBDA, "query_handler"))
sys.path.insert(0, os.path.join(_LAMBDA, "index_init"))

import pipelines  # noqa: E402
from retrieval import (  # noqa: E402
    BM25,
    DEEP_CANDIDATES,
    DENSE,
    DENSE_BM25,
    DENSE_BM25_DEEP,
    DENSE_BM25_LEX,
    DENSE_BM25_RRF,
    DENSE_BM25_SPARSE,
    HYBRID_MODES,
    MAX_SPARSE_TERMS,
    MODES,
    SINGLE_MODES,
    SPARSE,
    build_search_body,
    parse_hits,
    pipeline_key,
    sparse_subquery,
    uses_pipeline,
)

VEC = [0.1] * 1024


class BuildSearchBodyTest(unittest.TestCase):
    def test_osnovna_pretraga_ima_bm25_pa_knn(self):
        body = build_search_body("koji je port", VEC, 5)
        queries = body["query"]["hybrid"]["queries"]
        self.assertEqual(len(queries), 2)
        self.assertEqual(queries[0], {"match": {"text": {"query": "koji je port"}}})
        self.assertEqual(queries[1]["knn"]["dense_vector"]["k"], 5)
        self.assertEqual(len(queries[1]["knn"]["dense_vector"]["vector"]), 1024)

    def test_sparse_je_treci_podupit(self):
        body = build_search_body("q", VEC, 5, DENSE_BM25_SPARSE, {"7419": 0.3})
        queries = body["query"]["hybrid"]["queries"]
        self.assertEqual(len(queries), 3)
        self.assertIn("neural_sparse", queries[2])

    def test_size_prati_k(self):
        self.assertEqual(build_search_body("q", VEC, 7)["size"], 7)

    def test_vektori_se_ne_vracaju_iz_pretrage(self):
        excludes = build_search_body("q", VEC, 5)["_source"]["excludes"]
        self.assertIn("dense_vector", excludes)
        self.assertIn("sparse_weights", excludes)

    def test_nepoznat_oblik_i_los_k_su_greska(self):
        with self.assertRaises(ValueError):
            build_search_body("q", VEC, 5, "samo_bm25")
        with self.assertRaises(ValueError):
            build_search_body("q", VEC, 0)
        with self.assertRaises(ValueError):
            build_search_body("q", VEC, 0, BM25)


class SingleBranchTest(unittest.TestCase):
    """Pojedinacne grane: osnova za poredjenje sa hibridom."""

    WEIGHTS = {"7419": 0.3, "12": 0.1}

    def test_grana_je_tacno_podupit_hibrida(self):
        # Poredjenje ima smisla samo ako grana sama radi ISTO sto radi u hibridu.
        hybrid = build_search_body("q", VEC, 5, DENSE_BM25_SPARSE, self.WEIGHTS)
        subqueries = hybrid["query"]["hybrid"]["queries"]
        for mode, expected in zip((BM25, DENSE, SPARSE), subqueries):
            body = build_search_body("q", VEC, 5, mode, self.WEIGHTS)
            self.assertEqual(body["query"], expected, mode)

    def test_bez_hybrid_omotaca_i_bez_pipeline_a(self):
        for mode in SINGLE_MODES:
            body = build_search_body("q", VEC, 5, mode, self.WEIGHTS)
            self.assertNotIn("hybrid", body["query"], mode)
            self.assertFalse(uses_pipeline(mode), mode)
        for mode in HYBRID_MODES:
            self.assertTrue(uses_pipeline(mode), mode)

    def test_size_i_izuzeta_polja_kao_kod_hibrida(self):
        for mode in SINGLE_MODES:
            body = build_search_body("q", VEC, 7, mode, self.WEIGHTS)
            self.assertEqual(body["size"], 7)
            self.assertIn("dense_vector", body["_source"]["excludes"])

    def test_retka_grana_bez_tokena_ne_vraca_nista(self):
        body = build_search_body("q", VEC, 5, SPARSE, {})
        self.assertEqual(body["query"], {"match_none": {}})

    def test_svi_oblici(self):
        self.assertEqual(set(MODES), set(HYBRID_MODES) | set(SINGLE_MODES))
        self.assertEqual(len(MODES), 8)


class MergeVariantsTest(unittest.TestCase):
    """RRF, lex i deep menjaju samo spajanje ili broj kandidata, ne podupite."""

    def test_rrf_i_lex_salju_isti_upit_kao_osnova_kroz_drugi_pipeline(self):
        base = build_search_body("q", VEC, 5, DENSE_BM25)
        for mode in (DENSE_BM25_RRF, DENSE_BM25_LEX):
            self.assertEqual(build_search_body("q", VEC, 5, mode), base, mode)
            self.assertEqual(pipeline_key(mode), mode)
            self.assertNotEqual(pipeline_key(mode), pipeline_key(DENSE_BM25))

    def test_deep_ima_vise_kandidata_a_isti_pipeline(self):
        body = build_search_body("q", VEC, 5, DENSE_BM25_DEEP)
        hybrid = body["query"]["hybrid"]
        self.assertEqual(hybrid["pagination_depth"], DEEP_CANDIDATES)
        self.assertEqual(hybrid["queries"][1]["knn"]["dense_vector"]["k"], DEEP_CANDIDATES)
        self.assertEqual(hybrid["queries"][0], build_search_body("q", VEC, 5)["query"]["hybrid"]["queries"][0])
        self.assertEqual(body["size"], 5)                  # vraca se i dalje top 5
        self.assertEqual(pipeline_key(DENSE_BM25_DEEP), DENSE_BM25)

    def test_osnova_nema_pagination_depth(self):
        self.assertNotIn("pagination_depth", build_search_body("q", VEC, 5)["query"]["hybrid"])

    def test_pojedinacne_grane_nemaju_pipeline(self):
        for mode in SINGLE_MODES:
            self.assertIsNone(pipeline_key(mode))


class SparseSubqueryTest(unittest.TestCase):
    def test_tokeni_idu_kao_query_tokens(self):
        q = sparse_subquery({"10": 0.5, "20": 0.25})
        self.assertEqual(q, {"neural_sparse": {"sparse_weights": {
            "query_tokens": {"10": 0.5, "20": 0.25}}}})

    def test_odseca_na_najjace_tokene(self):
        weights = {str(i): float(i) for i in range(1, MAX_SPARSE_TERMS + 50)}
        tokens = sparse_subquery(weights)["neural_sparse"]["sparse_weights"]["query_tokens"]
        self.assertEqual(len(tokens), MAX_SPARSE_TERMS)
        self.assertIn(str(MAX_SPARSE_TERMS + 49), tokens)   # najjaci ostaje
        self.assertNotIn("1", tokens)                        # najslabiji otpada

    def test_deterministicki_redosled_pri_istoj_tezini(self):
        a = sparse_subquery({"b": 0.5, "a": 0.5, "c": 0.5})
        b = sparse_subquery({"c": 0.5, "a": 0.5, "b": 0.5})
        self.assertEqual(
            list(a["neural_sparse"]["sparse_weights"]["query_tokens"]),
            list(b["neural_sparse"]["sparse_weights"]["query_tokens"]),
        )

    def test_bez_tokena_je_i_dalje_validan_podupit(self):
        self.assertEqual(sparse_subquery({}), {"match_none": {}})
        self.assertEqual(sparse_subquery({"x": 0.0}), {"match_none": {}})
        self.assertEqual(sparse_subquery(None), {"match_none": {}})


class ParseHitsTest(unittest.TestCase):
    def test_rang_pocinje_od_jedan_i_prati_redosled(self):
        response = {"hits": {"hits": [
            {"_id": "d#00005", "_score": 0.9, "_source": {
                "chunk_id": "d#00005", "chunk_type": "image", "text": "caption",
                "image_ref": "images/d/000.png", "document_id": "d", "page": 2}},
            {"_id": "d#00000", "_score": 0.4, "_source": {
                "chunk_id": "d#00000", "chunk_type": "table", "text": "| a |"}},
        ]}}
        contexts = parse_hits(response)
        self.assertEqual([c["rank"] for c in contexts], [1, 2])
        self.assertEqual(contexts[0]["image_ref"], "images/d/000.png")
        self.assertIsNone(contexts[1]["image_ref"])

    def test_prazan_odgovor(self):
        self.assertEqual(parse_hits({}), [])


class PipelineSlaganjeTest(unittest.TestCase):
    """Tezine u pipeline-u moraju tacno odgovarati podupitima u upitu."""

    def test_isti_oblici_pretrage_sa_obe_strane(self):
        self.assertEqual({pipeline_key(m) for m in HYBRID_MODES}, set(pipelines.PIPELINE_NAMES))
        for mode in HYBRID_MODES:
            self.assertEqual(pipelines.SUBQUERY_COUNT[pipeline_key(mode)],
                             len(build_search_body("q", VEC, 5, mode, {"1": 0.5})
                                 ["query"]["hybrid"]["queries"]), mode)

    def test_broj_tezina_jednak_broju_podupita(self):
        for mode in HYBRID_MODES:
            body = build_search_body("q", VEC, 5, mode, {"1": 0.5})
            processor = pipelines.pipeline_definition(pipeline_key(mode))["phase_results_processors"][0]
            if "score-ranker-processor" in processor:
                continue   # RRF nema tezine
            weights = processor["normalization-processor"]["combination"]["parameters"]["weights"]
            self.assertEqual(len(weights), len(body["query"]["hybrid"]["queries"]), mode)

    def test_tezine_su_jednake_i_sabiraju_se_u_jedan(self):
        for count in (2, 3):
            weights = pipelines.equal_weights(count)
            self.assertAlmostEqual(sum(weights), 1.0, places=6)
            self.assertLess(max(weights) - min(weights), 0.001)

    def test_lex_daje_bm25_dve_trecine(self):
        # Isti udeo leksickog signala kao BM25 + sparse u obliku sa tri grane.
        weights = pipelines.weights_for(pipelines.DENSE_BM25_LEX)
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        three = pipelines.equal_weights(3)
        self.assertAlmostEqual(weights[0], three[0] + three[2], places=3)   # BM25 je prvi

    def test_rrf_pipeline(self):
        processor = (pipelines.pipeline_definition(pipelines.DENSE_BM25_RRF)
                     ["phase_results_processors"][0]["score-ranker-processor"])
        self.assertEqual(processor["combination"], {"technique": "rrf", "rank_constant": 60})

    def test_samo_eksperimentalni_smeju_da_ne_prodju(self):
        self.assertEqual(set(pipelines.EXPERIMENTAL),
                         {pipelines.DENSE_BM25_RRF, pipelines.DENSE_BM25_LEX})
        self.assertNotIn(pipelines.DENSE_BM25, pipelines.EXPERIMENTAL)

    def test_imena_pipeline_a_se_poklapaju_sa_cdk_konstantama(self):
        # Iste vrednosti stoje u SearchStack.PIPELINES (TypeScript).
        path = os.path.join(os.path.dirname(__file__), "..", "..", "lib", "search-stack.ts")
        with open(path, encoding="utf-8") as f:
            stack = f.read()
        for name in pipelines.PIPELINE_NAMES.values():
            self.assertIn("'{}'".format(name), stack)


if __name__ == "__main__":
    unittest.main()
