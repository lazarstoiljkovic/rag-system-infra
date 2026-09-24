"""
Testovi za sklapanje chunkova i manifest.

Pokretanje:
    python3 -m unittest discover -s test/python -v
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "extract_and_prepare"),
)

from elements import (  # noqa: E402
    IMAGE,
    TABLE,
    TEXT,
    Element,
    build_chunks,
    pending_manifest,
)

DOC = "prirucnik-v1"
URI = "s3://bucket/raw/prirucnik-v1.pdf"


class ElementValidacijaTest(unittest.TestCase):
    def test_nepoznat_tip_puca(self):
        with self.assertRaises(ValueError):
            Element(kind="video")

    def test_slika_bez_reference_puca(self):
        with self.assertRaises(ValueError):
            Element(kind=IMAGE)

    def test_slika_sa_referencom_prolazi(self):
        Element(kind=IMAGE, image_ref="images/x.png")


class BuildChunksTest(unittest.TestCase):
    def test_tabela_ostaje_jedan_chunk(self):
        el = Element(kind=TABLE, rows=[["Servis", "Port"], ["vLLM", "8000"]], page=3)
        chunks = build_chunks([el], DOC, URI)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_type"], TABLE)
        self.assertIn("| Servis | Port |", chunks[0]["text"])
        self.assertEqual(chunks[0]["page"], 3)
        self.assertIsNone(chunks[0]["image_ref"])

    def test_velika_tabela_se_i_dalje_ne_deli(self):
        rows = [["kolona_a", "kolona_b"]] + [["vrednost_" + str(i), "x" * 80] for i in range(60)]
        chunks = build_chunks([Element(kind=TABLE, rows=rows)], DOC, URI)
        self.assertEqual(len(chunks), 1)
        self.assertGreater(len(chunks[0]["text"]), 512)

    def test_tekst_se_deli_na_vise_chunkova(self):
        el = Element(kind=TEXT, text="x" * 1500, page=1)
        chunks = build_chunks([el], DOC, URI)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["chunk_type"] == TEXT for c in chunks))

    def test_prazan_tekst_ne_pravi_chunk(self):
        self.assertEqual(build_chunks([Element(kind=TEXT, text="   ")], DOC, URI), [])

    def test_prazna_tabela_ne_pravi_chunk(self):
        self.assertEqual(build_chunks([Element(kind=TABLE, rows=[])], DOC, URI), [])

    def test_slika_daje_prazan_tekst_i_referencu(self):
        el = Element(kind=IMAGE, image_ref="images/dijagram.png", page=7)
        chunks = build_chunks([el], DOC, URI)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_type"], IMAGE)
        self.assertEqual(chunks[0]["text"], "")
        self.assertEqual(chunks[0]["image_ref"], "images/dijagram.png")

    def test_chunk_id_je_determinisicki_i_jedinstven(self):
        els = [
            Element(kind=TEXT, text="a" * 1200),
            Element(kind=TABLE, rows=[["h"], ["v"]]),
            Element(kind=IMAGE, image_ref="images/a.png"),
        ]
        prvi = build_chunks(els, DOC, URI)
        drugi = build_chunks(els, DOC, URI)
        self.assertEqual([c["chunk_id"] for c in prvi], [c["chunk_id"] for c in drugi])
        self.assertEqual(len({c["chunk_id"] for c in prvi}), len(prvi))
        self.assertTrue(prvi[0]["chunk_id"].startswith(DOC + "#"))

    def test_sva_tri_tipa_zajedno(self):
        els = [
            Element(kind=TEXT, text="y" * 600, page=1),
            Element(kind=TABLE, rows=[["a", "b"], ["1", "2"]], page=2),
            Element(kind=IMAGE, image_ref="images/g.png", page=2),
        ]
        chunks = build_chunks(els, DOC, URI)
        tipovi = [c["chunk_type"] for c in chunks]
        self.assertIn(TEXT, tipovi)
        self.assertIn(TABLE, tipovi)
        self.assertIn(IMAGE, tipovi)
        self.assertTrue(all(c["document_id"] == DOC for c in chunks))
        self.assertTrue(all(c["source_uri"] == URI for c in chunks))


class ManifestTest(unittest.TestCase):
    def test_brojaci_se_slazu_sa_ukupnim(self):
        els = [
            Element(kind=TEXT, text="z" * 1500),
            Element(kind=TABLE, rows=[["a"], ["1"]]),
            Element(kind=IMAGE, image_ref="images/x.png"),
        ]
        chunks = build_chunks(els, DOC, URI)
        m = pending_manifest(chunks, DOC, URI)
        self.assertEqual(m["total"], len(chunks))
        self.assertEqual(sum(m["counts"].values()), m["total"])
        self.assertEqual(m["counts"][TABLE], 1)
        self.assertEqual(m["counts"][IMAGE], 1)

    def test_prazan_dokument(self):
        m = pending_manifest([], DOC, URI)
        self.assertEqual(m["total"], 0)
        self.assertEqual(sum(m["counts"].values()), 0)


if __name__ == "__main__":
    unittest.main()
