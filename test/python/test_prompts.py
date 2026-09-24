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


if __name__ == "__main__":
    unittest.main()
