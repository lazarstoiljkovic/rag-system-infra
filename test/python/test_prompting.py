"""Testovi za prompt generatora, varijante A i B."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "query_handler")
)

from prompting import (  # noqa: E402
    MAX_IMAGES,
    SYSTEM_PROMPT,
    VARIANT_A,
    VARIANT_B,
    build_messages,
    context_header,
    images_to_attach,
    prompt_fingerprint,
    text_only,
)


def _ctx(rank, ctype="text", text="tekst", image_ref=None, doc="d", page=1):
    return {"rank": rank, "chunk_type": ctype, "text": text, "image_ref": image_ref,
            "document_id": doc, "page": page}


CONTEXTS = [
    _ctx(1, "table", "| Parametar | Podrazumevano |"),
    _ctx(2, "image", "Veze: Klijent SDK -> Kestrel Gateway", "images/d/000.png", page=2),
    _ctx(3, "text", "Kestrel je distribuirani red poruka."),
]
URLS = {"images/d/000.png": "data:image/png;base64,AAAA"}


class AblacijaTest(unittest.TestCase):
    def test_tekst_je_identican_u_a_i_b(self):
        # Srz ablacije: B SAMO dodaje slike, nijedna rec se ne menja.
        a, _ = build_messages("Kom cvoru ruter salje upis?", CONTEXTS, VARIANT_A, {})
        b, _ = build_messages("Kom cvoru ruter salje upis?", CONTEXTS, VARIANT_B, URLS)
        self.assertEqual(text_only(a), text_only(b))

    def test_a_nikad_ne_salje_sliku(self):
        # Cak i kad bi handler greskom prosledio URL, A ga ne sme ugraditi.
        messages, attached = build_messages("q", CONTEXTS, VARIANT_A, URLS)
        parts = messages[1]["content"]
        self.assertFalse(any(p["type"] == "image_url" for p in parts))
        self.assertEqual(attached, [])

    def test_b_salje_sliku_odmah_posle_njenog_captiona(self):
        messages, attached = build_messages("q", CONTEXTS, VARIANT_B, URLS)
        parts = messages[1]["content"]
        idx = next(i for i, p in enumerate(parts) if p["type"] == "image_url")
        self.assertTrue(parts[idx - 1]["text"].startswith("[2] (slika, opis"))
        self.assertEqual(attached, ["images/d/000.png"])

    def test_sistemski_prompt_ne_pominje_slike(self):
        # Recenica o slikama bi postojala samo u B, ili bi u A lagala.
        self.assertNotIn("slik", SYSTEM_PROMPT.lower())


class ImagesToAttachTest(unittest.TestCase):
    def test_a_nema_slika(self):
        self.assertEqual(images_to_attach(CONTEXTS, VARIANT_A), [])

    def test_b_najvise_max_images_po_rangu(self):
        many = [_ctx(i, "image", "c", "images/d/{:03d}.png".format(i))
                for i in range(1, MAX_IMAGES + 3)]
        refs = images_to_attach(many, VARIANT_B)
        self.assertEqual(len(refs), MAX_IMAGES)
        self.assertEqual(refs[0], "images/d/001.png")

    def test_ista_slika_se_ne_salje_dvaput(self):
        dup = [_ctx(1, "image", "c", "images/d/000.png"),
               _ctx(2, "image", "c", "images/d/000.png")]
        self.assertEqual(images_to_attach(dup, VARIANT_B), ["images/d/000.png"])

    def test_nepoznata_varijanta(self):
        with self.assertRaises(ValueError):
            images_to_attach(CONTEXTS, "C")


class OblikPorukaTest(unittest.TestCase):
    def test_zaglavlje_konteksta(self):
        self.assertEqual(context_header(CONTEXTS[1]), "[2] (slika, opis, d, str. 2)")

    def test_pitanje_je_poslednje(self):
        messages, _ = build_messages("  Koji je port?  ", CONTEXTS, VARIANT_A, {})
        self.assertEqual(messages[1]["content"][-1]["text"], "Pitanje: Koji je port?")
        self.assertEqual(messages[0], {"role": "system", "content": SYSTEM_PROMPT})

    def test_otisak_prompta_je_stabilan(self):
        self.assertEqual(prompt_fingerprint(), prompt_fingerprint())
        self.assertEqual(len(prompt_fingerprint()), 12)


if __name__ == "__main__":
    unittest.main()


class PartSeparationTest(unittest.TestCase):
    """
    Sablon za razgovor modela Qwen spaja tekstualne delove BEZ razmaka. Kad
    se tekst izvora zavrsavao bez praznog reda, zalepio se za zaglavlje
    sledeceg (`...300 sekundi.[3] (tabela, ...)`), i model je u merenju
    2026-10-01 navodio izvor za jedan veci od pravog.
    """

    def _joined(self, messages):
        return "".join(p["text"] for p in messages[1]["content"] if p["type"] == "text")

    def test_tekst_izvora_se_ne_lepi_za_sledece_zaglavlje(self):
        contexts = [_ctx(1, text="prvi"), _ctx(2, text="drugi"), _ctx(3, text="treci")]
        joined = self._joined(build_messages("p?", contexts, VARIANT_A, {})[0])
        for marker in ("[2]", "[3]", "Pitanje:"):
            self.assertIn("\n\n" + marker, joined)

    def test_slika_je_unutar_bloka_svog_izvora(self):
        ref = "images/d/000.png"
        contexts = [_ctx(1, "image", "opis", image_ref=ref), _ctx(2, text="drugi")]
        content = build_messages("p?", contexts, VARIANT_B, {ref: "data:x"})[0][1]["content"]
        kinds = [p["type"] for p in content]
        i = kinds.index("image_url")
        self.assertTrue(content[i - 1]["text"].startswith("[1] "))
        self.assertTrue(content[i + 1]["text"].startswith("opis"))

    def test_otisak_zavisi_od_formata_poruke(self):
        import prompting
        before = prompting.prompt_fingerprint()
        prompting.PROMPT_FORMAT += 1
        try:
            self.assertNotEqual(before, prompting.prompt_fingerprint())
        finally:
            prompting.PROMPT_FORMAT -= 1
