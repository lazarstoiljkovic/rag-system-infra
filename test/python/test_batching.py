"""Testovi za grupisanje u batch-eve i spajanje sa vektorima."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "embed_chunks")
)

from batching import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    attach_embeddings,
    chunked,
    drop_empty,
    embeddable_text,
)


def _chunk(cid, text="tekst", ctype="text", image_ref=None):
    return {"chunk_id": cid, "text": text, "chunk_type": ctype, "image_ref": image_ref}


class ChunkedTest(unittest.TestCase):
    def test_deli_na_grupe(self):
        self.assertEqual(list(chunked(list(range(5)), 2)), [[0, 1], [2, 3], [4]])

    def test_prazan_niz(self):
        self.assertEqual(list(chunked([], 3)), [])

    def test_manje_od_velicine_daje_jednu_grupu(self):
        self.assertEqual(list(chunked([1, 2], 10)), [[1, 2]])

    def test_nijedan_element_se_ne_gubi(self):
        items = list(range(100))
        spojeno = [x for grupa in chunked(items, DEFAULT_BATCH_SIZE) for x in grupa]
        self.assertEqual(spojeno, items)

    def test_neispravna_velicina(self):
        with self.assertRaises(ValueError):
            list(chunked([1], 0))


class AttachEmbeddingsTest(unittest.TestCase):
    def test_spaja_po_redosledu(self):
        chunks = [_chunk("a"), _chunk("b")]
        vectors = [{"dense": [1.0], "sparse": {"x": 0.5}}, {"dense": [2.0], "sparse": {}}]
        out = attach_embeddings(chunks, vectors)
        self.assertEqual(out[0]["chunk_id"], "a")
        self.assertEqual(out[0]["dense_vector"], [1.0])
        self.assertEqual(out[0]["sparse_weights"], {"x": 0.5})
        self.assertEqual(out[1]["dense_vector"], [2.0])

    def test_nepoklapanje_duzina_puca(self):
        # Tiho krace poklapanje vezalo bi vektor za pogresan chunk.
        with self.assertRaises(ValueError):
            attach_embeddings([_chunk("a"), _chunk("b")], [{"dense": [1.0]}])

    def test_nedostajuci_sparse_postaje_prazan(self):
        out = attach_embeddings([_chunk("a")], [{"dense": [1.0]}])
        self.assertEqual(out[0]["sparse_weights"], {})

    def test_ne_menja_ulaz(self):
        chunks = [_chunk("a")]
        attach_embeddings(chunks, [{"dense": [1.0]}])
        self.assertNotIn("dense_vector", chunks[0])


class EmbeddableTextTest(unittest.TestCase):
    def test_za_sliku_se_embeduje_caption(self):
        # Potvrda da se i slike embeduju kroz ISTI tekstualni model, preko opisa.
        c = _chunk("s", text="Dijagram: Lambda salje zahtev ka vLLM-u.",
                   ctype="image", image_ref="images/x.png")
        self.assertEqual(embeddable_text(c), "Dijagram: Lambda salje zahtev ka vLLM-u.")

    def test_nedostajuci_tekst_daje_prazan_string(self):
        self.assertEqual(embeddable_text({"chunk_id": "x"}), "")


class DropEmptyTest(unittest.TestCase):
    def test_izbacuje_prazne_i_same_beline(self):
        chunks = [_chunk("a", "tekst"), _chunk("b", ""), _chunk("c", "   ")]
        self.assertEqual([c["chunk_id"] for c in drop_empty(chunks)], ["a"])

    def test_slika_bez_caption_a_se_izbacuje(self):
        neuspela = _chunk("s", text="", ctype="image", image_ref="images/x.png")
        self.assertEqual(drop_empty([neuspela]), [])


if __name__ == "__main__":
    unittest.main()
