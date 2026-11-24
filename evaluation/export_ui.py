"""
Snimak jednog merenja za korisnicku stranicu: `ui/snimljeno/`.

    python3 evaluation/export_ui.py --run-id eval-2026-10-02

Pravi `ui/snimljeno/snimljeno.json` (pitanja, odgovori A i B, ocene sudije,
delovi dokumenata koje je pretraga vratila) i kopira originalne slike u
`ui/snimljeno/img/`. `RagQueryStack` postavlja ceo `ui/` na stranicu, pa
stranica tada ima:

  - pogled "Rezultati merenja" (zbirna tabela i svih 106 pitanja);
  - rezervu u pogledu "Pitaj": kad sistem ne odgovara (GPU ili vektorska
    baza su ugaseni), pitanje iz skupa dobija SNIMLJEN odgovor, uvek
    oznacen kao snimljen.

Radi samo nad lokalnim fajlovima merenja (manifest, log.jsonl, scores.jsonl,
images/), bez AWS-a i bez instalacija. `ui/snimljeno/` je u .gitignore-u, kao i
rezultati iz kojih nastaje; slike na stranici su javne, sto je prihvatljivo
jer je korpus sinteticki.
"""

import argparse
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dataset import latest_by_key, load_questions, read_jsonl, run_dir  # noqa: E402

UI_DIR = os.path.join(HERE, "..", "ui", "snimljeno")
IMAGE_PREFIX = "images/"


def image_name(image_ref: Optional[str]) -> Optional[str]:
    """`images/doc/000.png` -> `doc__000.png` (isto ime kao u kesu sudije, bez prefiksa)."""
    if not image_ref:
        return None
    key = image_ref[len(IMAGE_PREFIX):] if image_ref.startswith(IMAGE_PREFIX) else image_ref
    return key.replace("/", "__")


def build_snapshot(questions: List[Dict[str, Any]], manifest: List[Dict[str, Any]],
                   log: List[Dict[str, Any]], scores: List[Dict[str, Any]],
                   run_id: str) -> Dict[str, Any]:
    """
    Jedan zapis po pitanju, sa oba odgovora. Delovi dokumenata se cuvaju jednom
    (`chunks`), a pitanje ima samo njihov redosled i skor: pretraga je u A i B
    ista, sto se ovde i proverava.
    """
    by_query = {item["queryId"]: item for item in log}
    entries = latest_by_key(manifest, "id", "variant")
    judged = latest_by_key(scores, "id", "variant")
    chunks: Dict[str, Dict[str, Any]] = {}
    out = []
    model = None
    dates: List[str] = []
    for q in questions:
        rec: Dict[str, Any] = {
            "id": q["id"], "q": q["pitanje"], "exp": q["odgovor"], "tip": q["tip"],
            "slika": bool(q.get("samo_na_slici")), "tesko": bool(q.get("tesko_za_opis")),
            "docs": list(q["dokumenti"]),
        }
        order = {}
        for variant in ("A", "B"):
            entry = entries.get((q["id"], variant))
            item = by_query.get((entry or {}).get("queryId"))
            if item is None or item.get("error"):
                break
            model = model or item.get("model")
            if item.get("createdAt"):
                dates.append(item["createdAt"])
            contexts = sorted(item["contexts"], key=lambda c: c["rank"])
            for c in contexts:
                chunks[c["chunkId"]] = {"doc": c["documentId"], "page": c.get("page"),
                                        "type": c["chunkType"], "text": c.get("text", ""),
                                        "img": image_name(c.get("imageRef"))}
            order[variant] = [[c["chunkId"], round(float(c.get("score") or 0), 4)] for c in contexts]
            score = judged.get((q["id"], variant), {})
            rec[variant] = {
                "ans": item.get("answer", ""),
                "att": [image_name(ref) for ref in item.get("attachedImages", [])],
                "acc": score.get("answer_accuracy"),
                "ms": {k: round(v) for k, v in (item.get("latencyMs") or {}).items()},
            }
        else:
            if [c for c, _ in order["A"]] != [c for c, _ in order["B"]]:
                raise ValueError("pretraga se razlikuje u A i B za pitanje {}".format(q["id"]))
            rec["ctx"] = order["A"]
            out.append(rec)
    return {"run": run_id, "date": min(dates)[:10] if dates else None, "model": model, "k": 5,
            "questions": out, "chunks": chunks}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--run-id", default="eval-2026-10-02")
    args = parser.parse_args()

    folder = run_dir(args.run_id)
    snapshot = build_snapshot(
        load_questions(),
        read_jsonl(os.path.join(folder, "manifest.jsonl")),
        read_jsonl(os.path.join(folder, "log.jsonl")),
        read_jsonl(os.path.join(folder, "scores.jsonl")),
        args.run_id,
    )
    if not snapshot["questions"]:
        sys.exit("nema uspesnih zapisa u {} — prvo run_queries.py i fetch_log.py".format(folder))

    if os.path.isdir(UI_DIR):
        shutil.rmtree(UI_DIR)
    os.makedirs(os.path.join(UI_DIR, "img"))

    # Slike iz kesa koji je napravio ragas_eval.py (images__<doc>__<n>.png).
    missing = []
    for chunk in snapshot["chunks"].values():
        name = chunk["img"]
        if not name:
            continue
        src = os.path.join(folder, "images", "images__" + name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(UI_DIR, "img", name))
        else:
            missing.append(name)
            chunk["img"] = None
    for q in snapshot["questions"]:
        for v in ("A", "B"):
            q[v]["att"] = [n for n in q[v]["att"] if n not in missing]

    path = os.path.join(UI_DIR, "snimljeno.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))
    unscored = sum(1 for q in snapshot["questions"] for v in ("A", "B") if q[v]["acc"] is None)
    print("{} pitanja, {} delova, {} slika -> {}".format(
        len(snapshot["questions"]), len(snapshot["chunks"]),
        len(os.listdir(os.path.join(UI_DIR, "img"))), os.path.relpath(path)))
    if missing:
        print("PAZNJA: slike nisu u kesu i nece biti prikazane: {}".format(", ".join(missing)))
    if unscored:
        print("PAZNJA: {} odgovora bez ocene sudije (pusti ragas_eval.py)".format(unscored))


if __name__ == "__main__":
    main()
