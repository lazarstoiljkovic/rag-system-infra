"""Testovi za sastavljanje bulk tela i citanje gresaka."""

import json
import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "index_chunks")
)

from bulk import build_bulk_body, failed_items, to_document  # noqa: E402

INDEX = "rag-chunks"


def _chunk(cid="doc#00000", ctype="text", image_ref=None):
    return {
        "chunk_id": cid, "document_id": "doc", "chunk_type": ctype,
        "text": "neki tekst", "dense_vector": [0.1, 0.2],
        "sparse_weights": {"1": 0.5}, "image_ref": image_ref,
        "source_uri": "s3://b/raw/doc.pdf", "page": 1,
    }


class BuildBulkBodyTest(unittest.TestCase):
    def test_par_linija_po_dokumentu(self):
        body = build_bulk_body([_chunk("a"), _chunk("b")], INDEX)
        linije = body.strip().split("\n")
        self.assertEqual(len(linije), 4)

    def test_zavrsava_se_novim_redom(self):
        # Izostavljen zavrsni \n je klasican uzrok nejasne greske iz OpenSearch-a.
        self.assertTrue(build_bulk_body([_chunk()], INDEX).endswith("\n"))

    def test_id_je_chunk_id(self):
        body = build_bulk_body([_chunk("doc#00007")], INDEX)
        akcija = json.loads(body.split("\n")[0])
        self.assertEqual(akcija["index"]["_id"], "doc#00007")
        self.assertEqual(akcija["index"]["_index"], INDEX)

    def test_determinizam_omogucava_prepisivanje(self):
        # Isti ulaz -> isti _id -> ponovni ingestion prepisuje, ne duplira.
        self.assertEqual(
            build_bulk_body([_chunk("x")], INDEX), build_bulk_body([_chunk("x")], INDEX)
        )

    def test_svaka_linija_je_validan_json(self):
        body = build_bulk_body([_chunk("a"), _chunk("b")], INDEX)
        for linija in body.strip().split("\n"):
            json.loads(linija)

    def test_prazan_ulaz_daje_prazno_telo(self):
        self.assertEqual(build_bulk_body([], INDEX), "")

    def test_chunk_bez_id_a_puca(self):
        los = _chunk()
        del los["chunk_id"]
        with self.assertRaises(ValueError):
            build_bulk_body([los], INDEX)

    def test_srpska_slova_ostaju_citljiva(self):
        c = _chunk()
        c["text"] = "Šifra: čačak"
        body = build_bulk_body([c], INDEX)
        self.assertIn("Šifra", body)


class ToDocumentTest(unittest.TestCase):
    def test_image_ref_postoji_i_kad_je_none(self):
        # Polje mora postojati u svakom dokumentu — na njemu stoji varijanta B.
        d = to_document(_chunk())
        self.assertIn("image_ref", d)
        self.assertIsNone(d["image_ref"])

    def test_image_ref_se_prenosi(self):
        d = to_document(_chunk(ctype="image", image_ref="images/doc/000.png"))
        self.assertEqual(d["image_ref"], "images/doc/000.png")

    def test_nedostajuci_sparse_postaje_prazan_objekat(self):
        c = _chunk()
        c["sparse_weights"] = None
        self.assertEqual(to_document(c)["sparse_weights"], {})


class FailedItemsTest(unittest.TestCase):
    def test_bez_gresaka(self):
        self.assertEqual(failed_items({"errors": False, "items": []}), [])

    def test_izdvaja_neuspele(self):
        # OpenSearch vraca HTTP 200 i kad pojedinacne stavke ne prodju.
        odgovor = {
            "errors": True,
            "items": [
                {"index": {"_id": "a", "status": 201}},
                {"index": {"_id": "b", "status": 400, "error": {"type": "mapper_parsing"}}},
            ],
        }
        neuspeli = failed_items(odgovor)
        self.assertEqual(len(neuspeli), 1)
        self.assertEqual(neuspeli[0]["_id"], "b")
        self.assertEqual(neuspeli[0]["status"], 400)


if __name__ == "__main__":
    unittest.main()
