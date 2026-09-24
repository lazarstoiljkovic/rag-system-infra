"""
Testovi za ciste funkcije pripreme chunkova.

Pokretanje (bez ijedne instalacije, stdlib unittest):
    python3 -m unittest discover -s test/python -v
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "lambda", "extract_and_prepare"),
)

from chunking import (  # noqa: E402
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    chunk_text,
    table_to_markdown,
)


class ChunkTextTest(unittest.TestCase):
    def test_prazan_tekst_ne_daje_chunkove(self):
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text("   \n\t  "), [])

    def test_kraci_od_size_daje_jedan_chunk(self):
        text = "a" * 100
        self.assertEqual(chunk_text(text), [text])

    def test_tacno_size_daje_jedan_chunk(self):
        text = "a" * DEFAULT_CHUNK_SIZE
        self.assertEqual(chunk_text(text), [text])

    def test_preklapanje_je_tacno_overlap_znakova(self):
        text = "".join(str(i % 10) for i in range(2000))
        chunks = chunk_text(text)
        self.assertGreater(len(chunks), 2)
        for prev, nxt in zip(chunks, chunks[1:]):
            self.assertEqual(prev[-DEFAULT_OVERLAP:], nxt[:DEFAULT_OVERLAP])

    def test_nijedan_znak_se_ne_gubi(self):
        text = "".join(str(i % 10) for i in range(2000))
        chunks = chunk_text(text)
        step = DEFAULT_CHUNK_SIZE - DEFAULT_OVERLAP
        # Sklapanje bez preklapajucih repova mora vratiti original.
        rebuilt = chunks[0] + "".join(c[DEFAULT_OVERLAP:] for c in chunks[1:])
        self.assertEqual(rebuilt, text)
        self.assertEqual(step, 462)

    def test_svi_chunkovi_osim_poslednjeg_su_pune_duzine(self):
        text = "x" * 1500
        chunks = chunk_text(text)
        for c in chunks[:-1]:
            self.assertEqual(len(c), DEFAULT_CHUNK_SIZE)
        self.assertLessEqual(len(chunks[-1]), DEFAULT_CHUNK_SIZE)

    def test_neispravni_parametri(self):
        with self.assertRaises(ValueError):
            chunk_text("abc", size=0)
        with self.assertRaises(ValueError):
            chunk_text("abc", overlap=-1)
        with self.assertRaises(ValueError):
            chunk_text("abc", size=50, overlap=50)


class TableToMarkdownTest(unittest.TestCase):
    def test_prazna_tabela(self):
        self.assertEqual(table_to_markdown([]), "")

    def test_osnovna_tabela_prvi_red_je_zaglavlje(self):
        rows = [["Servis", "Port"], ["vLLM", "8000"], ["bge-m3", "8001"]]
        self.assertEqual(
            table_to_markdown(rows),
            "| Servis | Port |\n| --- | --- |\n| vLLM | 8000 |\n| bge-m3 | 8001 |",
        )

    def test_eksplicitno_zaglavlje(self):
        out = table_to_markdown([["a", "b"]], header=["A", "B"])
        self.assertEqual(out, "| A | B |\n| --- | --- |\n| a | b |")

    def test_pipe_se_bekslesuje(self):
        out = table_to_markdown([["x|y", "z"]], header=["A", "B"])
        self.assertIn("x\\|y", out)
        # Zaglavlje + separator + jedan red.
        self.assertEqual(len(out.split("\n")), 3)

    def test_none_postaje_prazna_celija(self):
        out = table_to_markdown([[None, "z"]], header=["A", "B"])
        self.assertEqual(out.split("\n")[2], "|  | z |")

    def test_nejednaki_redovi_se_dopunjuju(self):
        out = table_to_markdown([["a"], ["b", "c", "d"]])
        lines = out.split("\n")
        # Najsiri red ima 3 kolone, pa svi redovi imaju 3.
        for line in lines:
            self.assertEqual(line.count("|"), 4)

    def test_novi_red_u_celiji_ne_lomi_tabelu(self):
        out = table_to_markdown([["prvi\ndrugi", "x"]], header=["A", "B"])
        self.assertEqual(len(out.split("\n")), 3)

    def test_determinizam(self):
        rows = [["Servis", "Port"], ["vLLM", "8000"]]
        self.assertEqual(table_to_markdown(rows), table_to_markdown(rows))


if __name__ == "__main__":
    unittest.main()
