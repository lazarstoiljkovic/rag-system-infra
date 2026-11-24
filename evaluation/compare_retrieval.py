"""
Poredjenje oblika pretrage: jedna tabela za vise prolaza.

    evaluation/.venv/bin/python evaluation/compare_retrieval.py \\
        --runs ret-R-bm25 ret-R-dense ret-R-sparse ret-R-dense_bm25 ret-R-dense_bm25_sparse \\
        --baseline ret-R-dense_bm25

Radi samo nad lokalnim fajlovima (manifest i log.jsonl svakog prolaza, posle
`fetch_log.py`), pa se moze ponavljati bez AWS-a i bez GPU-a.

Pitanje na koje odgovara: da li hibrid na ovom korpusu zaista pomaze, ili je
neka pojedinacna grana jednako dobra ili bolja. Bez pojedinacnih grana se to
samo pretpostavlja. Meri se varijanta A (pretraga je u A i B ista).

Poredjenje sa osnovom ide McNemar-ovim testom nad Hit@k po pitanju, iz istog
razloga kao kod A/B: ishodi su upareni (isto pitanje, dva oblika pretrage).
Uz sirovo p ide i Holm-ova korekcija, posebno za svaku grupu pitanja, jer se
sa osnovom poredi vise oblika odjednom.

Svi prolazi moraju biti nad ISTIM indeksom (isti opisi slika i isti vektori),
inace razlika meri i promenu indeksa. Zato se indeks pred ovo merenje puni iz
`embedded.json` (`reindex_from_s3.py`), a ne ponovnim ingestion-om.
"""

import argparse
import os
import sys
from typing import Any, Dict, List, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dataset import (ALL, HARD, IMAGE_ONLY, QUESTION_TYPES, RESULTS_DIR, TEXT,  # noqa: E402
                     join_records, load_questions, read_jsonl, run_dir)
from retrieval_metrics import first_relevant_rank, hit_at_k, summarize  # noqa: E402
from stats import holm, mcnemar_exact, paired_counts  # noqa: E402

# Kolone izvestaja: sva pitanja, pa po tipu izvora odgovora, pa zbirne grupe.
COLUMNS: Tuple[str, ...] = (ALL,) + QUESTION_TYPES + (IMAGE_ONLY, HARD)
# McNemar samo za sire grupe: na grupi od 7-20 pitanja test ionako nema snagu.
TEST_GROUPS = (ALL, TEXT, IMAGE_ONLY)


def in_group(record: Dict[str, Any], group: str) -> bool:
    return group in record["groups"] or group == record.get("type")


def run_label(manifest: List[Dict[str, Any]], run_id: str) -> str:
    """Oblik pretrage prolaza; prolaz sa vise oblika je greska u pokretanju."""
    modes = {row.get("retrieval") or "dense_bm25" for row in manifest}
    if len(modes) != 1:
        raise ValueError("prolaz {} mesa oblike pretrage: {}".format(run_id, sorted(modes)))
    return modes.pop()


def load_run(run_id: str, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    folder = run_dir(run_id)
    manifest = read_jsonl(os.path.join(folder, "manifest.jsonl"))
    if not manifest:
        raise ValueError("prolaz {} nema manifest u {}".format(run_id, folder))
    log = read_jsonl(os.path.join(folder, "log.jsonl"))
    if not log:
        raise ValueError("prolaz {} nema log.jsonl — prvo fetch_log.py".format(run_id))
    records = [r for r in join_records(questions, manifest, log) if r["variant"] == "A"]
    return {
        "run": run_id,
        "mode": run_label(manifest, run_id),
        "k": max((row.get("k") or 5) for row in manifest),
        "records": [r for r in records if not r["error"]],
        "failed": [r["id"] for r in records if r["error"]],
    }


def common_ids(runs: Sequence[Dict[str, Any]]) -> List[str]:
    """Pitanja sa uspesnim zapisom u SVIM prolazima — samo ona su uporediva."""
    sets = [{r["id"] for r in run["records"]} for run in runs]
    return sorted(set.intersection(*sets)) if sets else []


def metrics_table(runs: Sequence[Dict[str, Any]], ids: Sequence[str], k: int,
                  metric: str) -> List[str]:
    keep = set(ids)
    first = [r for r in runs[0]["records"] if r["id"] in keep]
    sizes = {c: sum(1 for r in first if in_group(r, c)) for c in COLUMNS}
    head = ["Oblik pretrage"] + ["{} ({})".format(c, sizes[c]) for c in COLUMNS if sizes[c]]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for run in runs:
        records = [r for r in run["records"] if r["id"] in keep]
        cells = [label(run, runs)]
        for c in COLUMNS:
            if sizes[c]:
                cells.append("{:.2f}".format(summarize([r for r in records if in_group(r, c)], k)[metric]))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def label(run: Dict[str, Any], runs: Sequence[Dict[str, Any]]) -> str:
    """Oblik pretrage, uz ime prolaza samo kad se oblik ponavlja (npr. provera ponovljivosti)."""
    same = [r for r in runs if r["mode"] == run["mode"]]
    return run["mode"] if len(same) == 1 else "{} ({})".format(run["mode"], run["run"])


def mcnemar_tests(baseline: Dict[str, Any], other: Dict[str, Any], ids: Sequence[str],
                  k: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    """McNemar nad Hit@k za svaku grupu, i pitanja gde se pogodak razlikuje."""
    base = {r["id"]: r for r in baseline["records"]}
    oth = {r["id"]: r for r in other["records"]}
    tests = []
    for group in TEST_GROUPS:
        qids = [q for q in ids if in_group(base[q], group)]
        a = [hit_at_k(base[q], k) for q in qids]
        b = [hit_at_k(oth[q], k) for q in qids]
        c = paired_counts(a, b)
        tests.append({"group": group, "n": len(qids), "hits_base": sum(a), "hits_other": sum(b),
                      "only_base": c["only_a"], "only_other": c["only_b"],
                      "p": mcnemar_exact(c["only_a"], c["only_b"])})
    differ = ["{} ({}→{})".format(q, first_relevant_rank(base[q]) or "–",
                                  first_relevant_rank(oth[q]) or "–")
              for q in ids if hit_at_k(base[q], k) != hit_at_k(oth[q], k)]
    return tests, differ


def with_holm(rows: List[Dict[str, Any]]) -> None:
    """Dodaje `p_holm`, korigovano unutar svake grupe preko svih poredjenih oblika."""
    for group in TEST_GROUPS:
        in_g = [r for r in rows if r["group"] == group]
        for row, adjusted in zip(in_g, holm([r["p"] for r in in_g])):
            row["p_holm"] = adjusted


def build_report(runs: List[Dict[str, Any]], baseline_run: str) -> List[str]:
    ks = {run["k"] for run in runs}
    if len(ks) != 1:
        raise ValueError("prolazi imaju razlicito k: {}".format(sorted(ks)))
    k = ks.pop()
    ids = common_ids(runs)
    baseline = next((r for r in runs if r["run"] == baseline_run), None)
    if baseline is None:
        raise ValueError("osnova {} nije medju prolazima".format(baseline_run))

    lines = ["# Poređenje oblika pretrage", "",
             "Prolazi: " + ", ".join("`{}` ({})".format(r["run"], r["mode"]) for r in runs) + ".",
             "Upoređeno je {} pitanja (uspešna u svim prolazima), k = {}, varijanta A.".format(len(ids), k)]
    for run in runs:
        if run["failed"]:
            lines.append("Neuspešna u `{}`: {}.".format(run["run"], ", ".join(run["failed"])))

    lines += ["", "## Hit@{}".format(k), ""] + metrics_table(runs, ids, k, "hit_at_k")
    lines += ["", "## MRR", ""] + metrics_table(runs, ids, k, "mrr")

    lines += ["", "## Poređenje sa osnovom (`{}`), McNemar nad Hit@{}".format(baseline["mode"], k), "",
              "p (Holm) je korigovano za broj poređenja u istoj grupi pitanja.", "",
              "| Oblik | Grupa | n | pogodaka osnova | pogodaka ovaj | samo osnova | samo ovaj "
              "| p (tačan) | p (Holm) |",
              "|---|---|---|---|---|---|---|---|---|"]
    rows: List[Dict[str, Any]] = []
    differences = []
    for run in runs:
        if run is baseline:
            continue
        tests, differ = mcnemar_tests(baseline, run, ids, k)
        rows += [dict(t, label=label(run, runs)) for t in tests]
        if differ:
            differences.append("- **{}**: {}".format(label(run, runs), ", ".join(differ)))
    with_holm(rows)
    for r in rows:
        lines.append("| {label} | {group} | {n} | {hits_base} | {hits_other} | {only_base} "
                     "| {only_other} | {p:.3f} | {p_holm:.3f} |".format(**r))
    if differences:
        lines += ["", "Pitanja gde se pogodak razlikuje od osnove (rang prvog relevantnog, osnova→ovaj):", ""]
        lines += differences
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--baseline", help="prolaz sa kojim se porede ostali (podrazumevano prvi dense_bm25)")
    parser.add_argument("--out", default="retrieval-poredjenje.md",
                        help="ime izvestaja u evaluation/results/")
    args = parser.parse_args()

    questions = load_questions()
    runs = [load_run(run_id, questions) for run_id in args.runs]
    baseline = args.baseline or next((r["run"] for r in runs if r["mode"] == "dense_bm25"),
                                     runs[0]["run"])
    lines = build_report(runs, baseline)

    path = os.path.join(RESULTS_DIR, args.out)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\n-> {}".format(os.path.relpath(path)))


if __name__ == "__main__":
    main()
