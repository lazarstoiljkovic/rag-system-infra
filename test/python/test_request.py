"""Testovi za citanje zahteva i zapis u query-log."""

import base64
import json
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "query_handler")
)

from records import build_log_item, to_dynamo  # noqa: E402
from request import (  # noqa: E402
    SNIPPET_CHARS,
    BadRequest,
    http_response,
    parse_request,
    public_sources,
)


def _api(body, b64=False):
    raw = json.dumps(body)
    if b64:
        raw = base64.b64encode(raw.encode()).decode()
    return {"requestContext": {}, "body": raw, "isBase64Encoded": b64}


class ParseRequestTest(unittest.TestCase):
    def test_podrazumevano_a_osnovna_pretraga_k5(self):
        req = parse_request(_api({"question": " Koji je port? "}))
        self.assertEqual(req, {"question": "Koji je port?", "variant": "A",
                               "retrieval": "dense_bm25", "k": 5, "evalRunId": None})

    def test_direktan_poziv_i_base64_telo_daju_isto(self):
        body = {"question": "q", "variant": "b", "retrieval": "DENSE_BM25_SPARSE",
                "k": 3, "evalRunId": "run-2026.09.26_a"}
        self.assertEqual(parse_request(body), parse_request(_api(body, b64=True)))
        self.assertEqual(parse_request(body)["variant"], "B")

    def test_neispravni_zahtevi(self):
        losi = [
            {},
            {"question": "   "},
            {"question": 42},
            {"question": "x" * 2001},
            {"question": "q", "variant": "C"},
            {"question": "q", "retrieval": "bm25"},
            {"question": "q", "k": 0},
            {"question": "q", "k": 21},
            {"question": "q", "k": "5"},
            {"question": "q", "k": True},
            {"question": "q", "evalRunId": "ima razmak"},
        ]
        for body in losi:
            with self.assertRaises(BadRequest, msg=body):
                parse_request(_api(body))

    def test_telo_koje_nije_json(self):
        with self.assertRaises(BadRequest):
            parse_request({"requestContext": {}, "body": "nije json"})
        with self.assertRaises(BadRequest):
            parse_request({"requestContext": {}, "body": "[1, 2]"})

    def test_http_odgovor(self):
        resp = http_response(400, {"error": "greska"})
        self.assertEqual(resp["statusCode"], 400)
        self.assertEqual(json.loads(resp["body"]), {"error": "greska"})
        self.assertIn("Access-Control-Allow-Origin", resp["headers"])


class PublicSourcesTest(unittest.TestCase):
    CTX = [
        {"rank": 1, "chunk_id": "d#00005", "chunk_type": "image", "text": "Veze: ...",
         "image_ref": "images/d/000.png", "document_id": "d", "page": 2, "score": 0.9},
        {"rank": 2, "chunk_id": "d#00006", "chunk_type": "image", "text": "Naslov: ...",
         "image_ref": "images/d/001.png", "document_id": "d", "page": 2, "score": 0.5},
        {"rank": 3, "chunk_id": "d#00001", "chunk_type": "text", "text": "x" * 1000,
         "image_ref": None, "document_id": "d", "page": 1, "score": 0.1},
    ]

    def _run(self, attached):
        return public_sources(self.CTX, attached, lambda ref: "https://signed/" + ref)

    def test_slika_dobija_link_tekst_ne(self):
        out = self._run([])
        self.assertEqual(out[0]["imageUrl"], "https://signed/images/d/000.png")
        self.assertIsNone(out[2]["imageUrl"])

    def test_oznaka_da_je_generator_video_sliku(self):
        out = self._run(["images/d/000.png"])
        self.assertEqual([s["sentToGenerator"] for s in out], [True, False, False])

    def test_dug_tekst_se_skracuje(self):
        text = self._run([])[2]["text"]
        self.assertEqual(len(text), SNIPPET_CHARS + 3)
        self.assertTrue(text.endswith("..."))


class LogItemTest(unittest.TestCase):
    REQ = {"question": "q", "variant": "B", "retrieval": "dense_bm25", "k": 5,
           "evalRunId": None}
    CTX = [{"rank": 1, "score": 0.873, "chunk_id": "d#00005", "chunk_type": "image",
            "text": "caption", "image_ref": "images/d/000.png", "document_id": "d",
            "page": 2}]

    def _item(self, **kw):
        args = dict(query_id="id", created_at="2026-09-26T18:00:00+00:00",
                    request=self.REQ, contexts=self.CTX, answer="odgovor [1]",
                    attached_images=["images/d/000.png"],
                    latencies_ms={"embed": 12.5, "total": 3000.0},
                    model="m", pipeline="rag-hybrid-dense-bm25",
                    prompt_fingerprint="abc123abc123")
        args.update(kw)
        return build_log_item(**args)

    def test_cuva_sve_sto_trazi_sudija(self):
        item = self._item()
        self.assertEqual(item["question"], "q")
        self.assertEqual(item["answer"], "odgovor [1]")
        self.assertEqual(item["contexts"][0]["text"], "caption")
        self.assertEqual(item["contexts"][0]["imageRef"], "images/d/000.png")
        self.assertEqual(item["attachedImages"], ["images/d/000.png"])

    def test_float_postaje_decimal(self):
        item = self._item()
        self.assertEqual(item["contexts"][0]["score"], Decimal("0.873"))
        self.assertEqual(item["latencyMs"]["embed"], Decimal("12.5"))

    def test_bez_eval_run_id_polje_izostaje(self):
        # GSI byEvalRun je redak: rucne probe iz UI-ja ne ulaze u njega.
        self.assertNotIn("evalRunId", self._item())
        self.assertNotIn("error", self._item())

    def test_greska_se_upisuje(self):
        self.assertEqual(self._item(error="timeout", answer="")["error"], "timeout")

    def test_to_dynamo_ne_dira_bool_i_int(self):
        self.assertEqual(to_dynamo({"a": True, "b": 3, "c": None}), {"a": True, "b": 3})


if __name__ == "__main__":
    unittest.main()
