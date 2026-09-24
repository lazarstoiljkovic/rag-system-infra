"""Testovi za izvodjenje identifikatora i S3 kljuceva."""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "extract_and_prepare"),
)

from naming import (  # noqa: E402
    IMAGES_PREFIX,
    document_id_from_key,
    image_key,
    manifest_keys,
)


class DocumentIdTest(unittest.TestCase):
    def test_skida_prefiks_i_ekstenziju(self):
        self.assertEqual(document_id_from_key("raw/prirucnik.pdf"), "prirucnik")

    def test_radi_i_bez_raw_prefiksa(self):
        self.assertEqual(document_id_from_key("prirucnik.docx"), "prirucnik")

    def test_razmaci_i_zagrade_postaju_donja_crta(self):
        self.assertEqual(
            document_id_from_key("raw/Prirucnik v2 (final).pdf"), "Prirucnik_v2_final"
        )

    def test_nema_vodecih_ni_pratecih_crta(self):
        out = document_id_from_key("raw/  (nesto)  .pdf")
        self.assertFalse(out.startswith("_"))
        self.assertFalse(out.endswith("_"))

    def test_determinizam(self):
        k = "raw/Neki Dokument 2024.pdf"
        self.assertEqual(document_id_from_key(k), document_id_from_key(k))

    def test_ime_bez_ijednog_alfanumerika_puca(self):
        # Invarijant je "mora imati bar jedan alfanumericki znak", ne "mora
        # imati ekstenziju" — za ekstenziju je zaduzen extract().
        for kljuc in ("raw/___.pdf", "raw/ .pdf", "raw/---.docx"):
            with self.assertRaises(ValueError, msg=kljuc):
                document_id_from_key(kljuc)

    def test_skriveni_fajl_prolazi_ovde_a_pada_u_extract_u(self):
        # `raw/.pdf` -> "pdf": cudno, ali bezopasno. Takav kljuc nema pravu
        # ekstenziju, pa ga extract() odbija kao nepodrzan format.
        self.assertEqual(document_id_from_key("raw/.pdf"), "pdf")
        import extractor
        with self.assertRaises(ValueError):
            extractor.extract("raw/.pdf", lambda b, s: "x")

    def test_ugnjezdeni_direktorijum(self):
        self.assertEqual(document_id_from_key("raw/2024/q1/izvestaj.pdf"), "izvestaj")


class ImageKeyTest(unittest.TestCase):
    def test_oblik_kljuca(self):
        self.assertEqual(image_key("doc", 0, "png"), IMAGES_PREFIX + "doc/000.png")
        self.assertEqual(image_key("doc", 12, "jpeg"), IMAGES_PREFIX + "doc/012.jpeg")

    def test_tacka_u_ekstenziji_se_skida(self):
        self.assertEqual(image_key("doc", 1, ".PNG"), IMAGES_PREFIX + "doc/001.png")

    def test_prazna_ekstenzija_daje_png(self):
        self.assertEqual(image_key("doc", 2, ""), IMAGES_PREFIX + "doc/002.png")

    def test_redosled_je_rastuci_i_bez_sudara(self):
        kljucevi = {image_key("doc", i, "png") for i in range(200)}
        self.assertEqual(len(kljucevi), 200)


class ManifestKeysTest(unittest.TestCase):
    def test_dva_odvojena_objekta(self):
        chunks, manifest = manifest_keys("doc")
        self.assertNotEqual(chunks, manifest)
        self.assertTrue(chunks.endswith("chunks.json"))
        self.assertTrue(manifest.endswith("manifest.json"))
        self.assertTrue(chunks.startswith("manifests/doc/"))


if __name__ == "__main__":
    unittest.main()
