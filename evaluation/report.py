"""
Izvestaj jednog evaluacionog prolaza: `report.md` u direktorijumu prolaza.

    evaluation/.venv/bin/python evaluation/report.py --run-id R

Radi samo nad lokalnim fajlovima (manifest, log, scores-*.jsonl, manual.csv).

Rucna ocena je zlatni standard za tacnost: `manual.csv` se pravi prazan pri
prvom pokretanju, kolona `tacno` se popuni sa 1 ili 0, i izvestaj se pusti
ponovo. Sudija se poredi sa njom (Cohen-ova kapa).
"""

import argparse
import csv
import math
import os
import sys
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dataset import (GROUPS, join_records, latest_by_key,  # noqa: E402
                     load_questions, read_jsonl, run_dir)
from retrieval_metrics import same_retrieval, summarize  # noqa: E402
from stats import cohen_kappa, mcnemar_chi2, mcnemar_exact, mean, paired_counts  # noqa: E402

# AnswerAccuracy daje 0, 0.25, 0.5, 0.75 ili 1 (prosek dva poziva sudiji na
# skali 0/2/4). "Tacno" znaci da nijedan od dva poziva nije dao 0 i da bar
# jedan nije "delimicno": prag 0.75.
ACCURACY_THRESHOLD = 0.75

MANUAL_FIELDS = ["id", "variant", "grupe", "pitanje", "ocekivano", "odgovor", "tacno"]


def fmt(x: float, digits: int = 2) -> str:
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else "{:.{}f}".format(x, digits)


def load_manual(path: str, records: List[Dict[str, Any]]) -> Dict[tuple, Optional[bool]]:
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANUAL_FIELDS)
            writer.writeheader()
            for r in records:
                writer.writerow({"id": r["id"], "variant": r["variant"],
                                 "grupe": " ".join(r["groups"][1:]), "pitanje": r["question"],
                                 "ocekivano": r["reference"], "odgovor": r["answer"], "tacno": ""})
        print("napravljen prazan {} — popuniti kolonu 'tacno' (1/0)".format(os.path.relpath(path)))
        return {}
    out: Dict[tuple, Optional[bool]] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value = (row.get("tacno") or "").strip()
            out[(row["id"], row["variant"])] = None if value == "" else value in ("1", "da", "true")
    return out


def ab_section(title: str, by_key: Dict[tuple, Optional[bool]], records, lines: List[str]) -> None:
    """Tacnost A naspram B po grupama, sa McNemar-ovim testom."""
    lines += ["", "### " + title, "",
              "| Grupa | n | A tačno | B tačno | samo A | samo B | p (tačan) | p (χ²) |",
              "|---|---|---|---|---|---|---|---|"]
    ids = sorted({r["id"] for r in records})
    groups_by_id = {r["id"]: r["groups"] for r in records}
    for group in GROUPS:
        a, b = [], []
        for qid in ids:
            if group not in groups_by_id[qid]:
                continue
            va, vb = by_key.get((qid, "A")), by_key.get((qid, "B"))
            if va is None or vb is None:
                continue
            a.append(va)
            b.append(vb)
        if not a:
            continue
        c = paired_counts(a, b)
        _, p_chi = mcnemar_chi2(c["only_a"], c["only_b"])
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            group, len(a), sum(a), sum(b), c["only_a"], c["only_b"],
            fmt(mcnemar_exact(c["only_a"], c["only_b"]), 3), fmt(p_chi, 3)))
    discordant = [(qid, "A" if by_key.get((qid, "A")) else "B") for qid in ids
                  if by_key.get((qid, "A")) is not None and by_key.get((qid, "B")) is not None
                  and by_key[(qid, "A")] != by_key[(qid, "B")]]
    if discordant:
        lines += ["", "Pitanja na kojima se varijante razlikuju (tačna je navedena): " +
                  ", ".join("{} ({})".format(q, v) for q, v in discordant)]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    folder = run_dir(args.run_id)
    manifest = read_jsonl(os.path.join(folder, "manifest.jsonl"))
    all_records = join_records(load_questions(), manifest,
                               read_jsonl(os.path.join(folder, "log.jsonl")))
    records = [r for r in all_records if not r["error"]]
    failed = [r for r in all_records if r["error"]]
    k = max((e.get("k") or 5) for e in manifest) if manifest else 5

    lines = ["# Evaluacija: {}".format(args.run_id), "",
             "Odgovoreno: {} od {} (pitanje × varijanta); neuspešno: {}.".format(
                 len(records), len(all_records), len(failed))]
    if failed:
        lines.append("Neuspešna: " + ", ".join("{} {} ({})".format(r["id"], r["variant"], r["error"][:60])
                                              for r in failed))
    seconds = [e["seconds"] for e in manifest if not e.get("error") and e.get("seconds")]
    if seconds:
        lines.append("Trajanje obrade pitanja: prosečno {} s, najviše {} s.".format(
            fmt(sum(seconds) / len(seconds), 1), fmt(max(seconds), 1)))

    # --- pretraga --------------------------------------------------------
    by_variant = {(r["id"], r["variant"]): r for r in records}
    a_records = [r for r in records if r["variant"] == "A"]
    pairs = [(by_variant[(r["id"], "A")], by_variant.get((r["id"], "B"))) for r in a_records]
    mismatched = [a["id"] for a, b in pairs if b is not None and not same_retrieval(a, b)]
    lines += ["", "## Pretraga (varijanta A; k = {})".format(k), "",
              "| Grupa | n | Hit@{} | MRR | odziv dokumenata |".format(k), "|---|---|---|---|---|"]
    for group in GROUPS:
        s = summarize([r for r in a_records if group in r["groups"]], k)
        if s["n"]:
            lines.append("| {} | {} | {} | {} | {} |".format(
                group, s["n"], fmt(s["hit_at_k"]), fmt(s["mrr"]), fmt(s["doc_recall"])))
    lines.append("")
    lines.append("Pretraga u A i B se razlikovala za: {}.".format(", ".join(mismatched) or "nijedno pitanje"))

    # --- tacnost ----------------------------------------------------------
    lines += ["", "## Tačnost odgovora"]
    manual = load_manual(os.path.join(folder, "manual.csv"), records)
    if any(v is not None for v in manual.values()):
        ab_section("Ručna ocena", manual, records, lines)

    scores = latest_by_key(read_jsonl(os.path.join(folder, "scores.jsonl")), "id", "variant")
    judge_correct = {key: (None if math.isnan(row["answer_accuracy"])
                           else row["answer_accuracy"] >= ACCURACY_THRESHOLD)
                     for key, row in scores.items()}
    if scores:
        ab_section("Sudija (AnswerAccuracy ≥ {})".format(ACCURACY_THRESHOLD),
                   judge_correct, records, lines)

    # --- RAGAS metrike ----------------------------------------------------
    if scores:
        model = next(iter(scores.values())).get("judgeModel", "")
        lines += ["", "## RAGAS metrike (sudija {})".format(model), "",
                  "| Grupa | Var. | n | faithfulness | mm_faithfulness | answer_accuracy | context_recall |",
                  "|---|---|---|---|---|---|---|"]
        for group in GROUPS:
            for variant in ("A", "B"):
                rows = [scores[(r["id"], variant)] for r in records
                        if r["variant"] == variant and group in r["groups"]
                        and (r["id"], variant) in scores]
                if rows:
                    lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
                        group, variant, len(rows),
                        *(fmt(mean(row[m] for row in rows)) for m in
                          ("faithfulness", "mm_faithfulness", "answer_accuracy", "context_recall"))))
        errors = [key for key, row in scores.items() if row.get("errors")]
        if errors:
            lines.append("")
            lines.append("Metrike sa greškom: " + ", ".join("{} {}".format(*e) for e in errors))

    # --- slaganje sudije sa rucnom ocenom ----------------------------------
    common = [(manual[key], judge_correct[key]) for key in manual
              if manual[key] is not None and judge_correct.get(key) is not None]
    if common:
        agree = sum(1 for p, q in common if p == q) / len(common)
        lines += ["", "## Slaganje sudije sa ručnom ocenom (tačnost)", "",
                  "n = {}, slaganje {}, Cohen-ova kapa {}.".format(
                      len(common), fmt(agree), fmt(cohen_kappa(common)))]

    path = os.path.join(folder, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\n-> {}".format(os.path.relpath(path)))


if __name__ == "__main__":
    main()
