"""Testovi za izbor prompta pri captioning-u."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "caption_chunk")
)

from prompts import (  # noqa: E402
    CHART,
    CHART_PROMPT,
    DIAGRAM,
    DIAGRAM_PROMPT,
    classify,
    clean_caption,
    prompt_for,
)


class ClassifyTest(unittest.TestCase):
    def test_prepoznaje_grafikon(self):
        for odgovor in ("grafikon", "Grafikon.", "GRAFIKON", "stubicasti grafikon",
                        "chart", "linijski prikaz", "tortni dijagram"):
            self.assertEqual(classify(odgovor), CHART, msg=odgovor)

    def test_prepoznaje_dijagram(self):
        for odgovor in ("dijagram", "Dijagram.", "dijagram arhitekture",
                        "Ovo je dijagram sa komponentama"):
            self.assertEqual(classify(odgovor), DIAGRAM, msg=odgovor)

    def test_rec_dijagram_ne_daje_lazni_pogodak_na_graf(self):
        # "dijagram" sadrzi "gram", ne "graf" — ovo je zakljucano testom jer je
        # bilo pravi rizik kad se trazi podniz.
        self.assertNotIn("graf", "dijagram")
        self.assertEqual(classify("dijagram"), DIAGRAM)

    def test_prazan_i_none_daju_podrazumevani_dijagram(self):
        self.assertEqual(classify(""), DIAGRAM)
        self.assertEqual(classify(None), DIAGRAM)
        self.assertEqual(classify("   "), DIAGRAM)

    def test_neodlucan_odgovor_pada_na_dijagram(self):
        self.assertEqual(classify("ne mogu da odredim"), DIAGRAM)


class PromptForTest(unittest.TestCase):
    def test_bira_odgovarajuci_prompt(self):
        self.assertEqual(prompt_for(CHART), CHART_PROMPT)
        self.assertEqual(prompt_for(DIAGRAM), DIAGRAM_PROMPT)

    def test_nepoznata_vrsta_pada_na_dijagram(self):
        self.assertEqual(prompt_for("nesto"), DIAGRAM_PROMPT)

    def test_promptovi_su_stvarno_razliciti(self):
        # Specifikacija trazi DVA RAZLICITA prompta, ne jedan opsti.
        self.assertNotEqual(DIAGRAM_PROMPT, CHART_PROMPT)

    def test_dijagram_prompt_trazi_pravac_strelica(self):
        # Bez pravca, "A zove B" i "B zove A" imaju isti opis.
        self.assertIn("PRAVAC", DIAGRAM_PROMPT)

    def test_chart_prompt_trazi_tacne_vrednosti_i_ose(self):
        # Bez brojeva je caption za varijantu A bezvredan.
        self.assertIn("TACNE VREDNOSTI", CHART_PROMPT)
        self.assertIn("ose", CHART_PROMPT)

    def test_promptovi_zabranjuju_pogadjanje(self):
        self.assertIn("Ne tumaci", DIAGRAM_PROMPT)
        self.assertIn("umesto da je pogodis", CHART_PROMPT)

    def test_promptovi_traze_da_se_uputstva_ne_ponavljaju(self):
        # Prolaz 2026-09-26: caption je ponavljao tekst prompta, sto je sum u
        # embedding-u i BM25 — i to isti sum u svakom captionu.
        for prompt in (DIAGRAM_PROMPT, CHART_PROMPT):
            self.assertIn("bez ponavljanja ovih uputstava", prompt)

    def test_promptovi_zadaju_sablon_odgovora(self):
        for polje in ("Komponente:", "Veze:", "Granice:"):
            self.assertIn(polje, DIAGRAM_PROMPT)
        for polje in ("Tip:", "X osa:", "Y osa:", "Vrednosti:", "Legenda:"):
            self.assertIn(polje, CHART_PROMPT)

    def test_dijagram_prompt_trazi_svaku_strelicu(self):
        # Prolaz 2026-09-26: izostavljena je jedna od sest strelica.
        self.assertIn("SVAKU strelicu", DIAGRAM_PROMPT)
        self.assertIn("nijedna strelica nije izostavljena", DIAGRAM_PROMPT)


class CleanCaptionTest(unittest.TestCase):
    # Stvarni izlaz modela iz prolaza 2026-09-26 (skracen).
    STVARNI = ("Naslov: Propusnost Kestrel-a po verziji\nTip: stubicasti\n"
               "Vrednosti:\n- v3.1: 27.9\nLegenda: nema\n\n"
               "Pravila:\n- TACNE VREDNOSTI za svaku tacku ili stubic: 27.9\n")

    def test_odseca_blok_pravila(self):
        cist = clean_caption(self.STVARNI)
        self.assertTrue(cist.endswith("Legenda: nema"))
        self.assertNotIn("Pravila", cist)

    def test_varijante_zapisa_naslova(self):
        for naslov in ("Pravila:", "**Pravila:**", "  PRAVILA :"):
            self.assertEqual(clean_caption("Tip: x\n" + naslov + "\n- y"), "Tip: x")

    def test_rec_pravila_usred_reda_se_ne_dira(self):
        tekst = "Veze:\n- Evaluator pravila -> Budilnik: alarm"
        self.assertEqual(clean_caption(tekst), tekst)

    def test_prazno(self):
        self.assertEqual(clean_caption(None), "")
        self.assertEqual(clean_caption("  x  "), "x")

    def test_sablon_je_poslednji_deo_prompta(self):
        # Model nastavlja ono sto je poslednje; pravila idu pre sablona.
        for prompt, poslednje in ((DIAGRAM_PROMPT, "Granice:"), (CHART_PROMPT, "Legenda:")):
            self.assertLess(prompt.index("Pravila:"), prompt.index(poslednje))
            self.assertNotIn("\n- ", prompt[prompt.index(poslednje):])


if __name__ == "__main__":
    unittest.main()
