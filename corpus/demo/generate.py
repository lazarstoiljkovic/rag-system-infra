"""
Generator demo korpusa i provera pitanja.

    python3 -m venv /tmp/corpus-venv
    /tmp/corpus-venv/bin/pip install PyMuPDF==1.24.14 python-docx==1.1.2 matplotlib
    /tmp/corpus-venv/bin/python corpus/demo/generate.py

Pravi `corpus/demo/dokumenti/` (22 dokumenta, PDF i DOCX) i `pitanja.json`, pa:

  1. proverava svako pitanje (vidi `questions.py`): odgovor "samo na slici" ne
     sme se naci ni u jednom tekstu korpusa, a mora postojati na slici; ostali
     odgovori moraju postojati u tekstu navedenih dokumenata;
  2. pusta svaki dokument kroz PRAVI `extractor.py` i `build_chunks` iz
     Lambde, i ispisuje broj chunkova po tipu — kao sto ce ih videti ingestion.

Izlazi sa greskom ako ijedna provera padne, pa se neispravan korpus ne moze
tiho iskoristiti za demo ili evaluaciju.
"""

import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "lambda", "extract_and_prepare"))

from documents import AUTHOR, DOCUMENTS as BASE_DOCUMENTS  # noqa: E402
from documents_dodatni import DOCUMENTS_DODATNI  # noqa: E402
from questions import QUESTIONS as BASE_QUESTIONS  # noqa: E402
from questions_dodatna import QUESTIONS_DODATNA, izmene_postojecih  # noqa: E402

# Prosirenje (2026-10-01): novi dokumenti i pitanja su u zasebnim modulima,
# a postojeca pitanja koja ometaci (stare verzije dokumenata) cine
# dvosmislenim dobijaju precizniji tekst (`izmene_postojecih`).
DOCUMENTS = BASE_DOCUMENTS + DOCUMENTS_DODATNI
QUESTIONS = izmene_postojecih(BASE_QUESTIONS) + QUESTIONS_DODATNA
from render import extracted_text, render_docx, render_pdf  # noqa: E402

OUT_DIR = os.path.join(HERE, "dokumenti")


def _norm(text):
    return re.sub(r"\s+", " ", text).lower()


def _figure_text(blocks):
    """Sve sto je ispisano NA slikama dokumenta: natpisi, oznake i vrednosti."""
    parts = []
    for kind, content in blocks:
        if kind != "figure":
            continue
        spec = content["spec"]
        kind = spec.get("kind")
        fmt = spec.get("fmt", "{:.1f}")
        if "nodes" in spec:
            parts += [label for _, _, label in spec["nodes"].values()]
            parts += [edge[2] for edge in spec["edges"]]
            parts += [group[4] for group in spec.get("groups", [])]
        elif "participants" in spec:
            parts += list(spec["participants"]) + [m[2] for m in spec["messages"]]
        elif kind in ("multiline", "grouped"):
            parts += [spec["title"], spec["x_label"], spec["y_label"]]
            parts += list(spec["categories"]) + list(spec["series"])
            if kind == "grouped":   # vrednosti su ispisane samo na grupisanim
                parts += [fmt.format(v) for vals in spec["series"].values() for v in vals]
        elif kind == "pie":
            parts += [spec["title"]] + list(spec["labels"])
            parts += [fmt.format(v) + "%" for v in spec["values"]]
        elif kind == "gantt":
            parts += [spec["title"]] + list(spec["months"]) + [t[0] for t in spec["tasks"]]
        else:
            fmt = spec.get("fmt", "{:.1f}")
            parts += [spec["title"], spec["x_label"], spec["y_label"]]
            parts += list(spec["categories"]) + [fmt.format(v) for v in spec["values"]]
    return " ".join(parts)


def _variants(key):
    """Broj sa tackom trazi se i sa zarezom (22.4 i 22,4)."""
    out = {_norm(key)}
    if re.fullmatch(r"\d+\.\d+", key):
        out.add(_norm(key.replace(".", ",")))
    return out


def check_questions(texts, figures):
    errors = []
    all_text = " ".join(texts.values())
    ids = set()
    for q in QUESTIONS:
        if q["id"] in ids:
            errors.append("{}: dupli id".format(q["id"]))
        ids.add(q["id"])
        for doc in q["dokumenti"]:
            if doc not in texts:
                errors.append("{}: nepoznat dokument {}".format(q["id"], doc))
        if q.get("tesko_za_opis") and not q.get("samo_na_slici"):
            errors.append("{}: 'tesko_za_opis' ima smisla samo uz 'samo_na_slici'".format(q["id"]))
        if q.get("naziv_i_u_tekstu") and not (q.get("samo_na_slici") and q.get("napomena")):
            errors.append("{}: 'naziv_i_u_tekstu' trazi 'samo_na_slici' i obrazlozenje u "
                          "'napomena'".format(q["id"]))
        for key in q["dokaz"]:
            if q.get("samo_na_slici"):
                # Kao zasebna rec, da "71" ne bi "nasao" u "1971" i slicno.
                # Izuzetak `naziv_i_u_tekstu`: odgovor je naziv (servisa,
                # projekta) koji postoji i u tekstu, ali cinjenica — koji od
                # njih — postoji samo na slici. Curenje se tada ne proverava,
                # a pitanje mora imati obrazlozenje u `napomena`.
                leaks = [] if q.get("naziv_i_u_tekstu") else [
                    v for v in _variants(key)
                    if re.search(r"(?<![\w.,]){}(?![\w])".format(re.escape(v)), all_text)]
                if leaks:
                    errors.append("{}: '{}' postoji u TEKSTU korpusa, a oznaceno je kao "
                                  "samo na slici".format(q["id"], key))
                if not any(_norm(key) in figures[d] for d in q["dokumenti"]):
                    errors.append("{}: '{}' ne postoji ni na jednoj slici dokumenta".format(
                        q["id"], key))
            elif not any(_norm(key) in texts[d] for d in q["dokumenti"]):
                errors.append("{}: '{}' ne postoji u tekstu {}".format(
                    q["id"], key, q["dokumenti"]))
    return errors


def chunk_summary(path):
    """Isti put kao ExtractAndPrepare u Lambdi, sa laznim sink-om za slike."""
    from elements import build_chunks
    from extractor import extract

    counter = {"n": 0}

    def sink(_data, ext):
        counter["n"] += 1
        return "images/test/{:03d}.{}".format(counter["n"], ext)

    chunks = build_chunks(extract(path, sink), "doc", "s3://x/raw/doc")
    counts = {"text": 0, "table": 0, "image": 0}
    for chunk in chunks:
        counts[chunk["chunk_type"]] += 1
    return counts


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # Stari izlazi se brisu: ceo `dokumenti/` ide u `raw/`, pa bi dokument
    # preimenovan ili izbacen iz DOCUMENTS inace tiho usao u indeks.
    for stale in os.listdir(OUT_DIR):
        if stale.endswith((".pdf", ".docx")):
            os.remove(os.path.join(OUT_DIR, stale))
    workdir = tempfile.mkdtemp()
    texts, figures, paths = {}, {}, {}

    for name, fmt, title, blocks in DOCUMENTS:
        path = os.path.join(OUT_DIR, "{}.{}".format(name, fmt))
        (render_pdf if fmt == "pdf" else render_docx)(blocks, path, workdir, title, AUTHOR)
        paths[name] = path
        texts[name] = _norm(extracted_text(path))
        figures[name] = _norm(_figure_text(blocks))

    errors = check_questions(texts, figures)

    print("dokument                          chunkovi (tekst/tabela/slika)")
    total = {"text": 0, "table": 0, "image": 0}
    for name, path in paths.items():
        counts = chunk_summary(path)
        for k in total:
            total[k] += counts[k]
        print("  {:32s} {:>3d} / {} / {}".format(
            os.path.basename(path), counts["text"], counts["table"], counts["image"]))
    print("  {:32s} {:>3d} / {} / {}".format("UKUPNO", total["text"], total["table"],
                                            total["image"]))

    print("dokumenata: {}".format(len(DOCUMENTS)))
    with open(os.path.join(HERE, "pitanja.json"), "w", encoding="utf-8") as f:
        json.dump(QUESTIONS, f, ensure_ascii=False, indent=2)
    only_image = sum(1 for q in QUESTIONS if q.get("samo_na_slici"))
    hard = sum(1 for q in QUESTIONS if q.get("tesko_za_opis"))
    multi = sum(1 for q in QUESTIONS if len(q["dokumenti"]) > 1)
    print("pitanja: {} (samo na slici: {}, od toga tesko za opis: {}; kroz vise "
          "dokumenata: {})".format(len(QUESTIONS), only_image, hard, multi))

    if errors:
        print("\nPROVERA PITANJA NIJE PROSLA:")
        for error in errors:
            print("  -", error)
        sys.exit(1)
    print("provera pitanja: OK")


if __name__ == "__main__":
    main()
