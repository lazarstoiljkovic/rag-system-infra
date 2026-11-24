"""
Postavlja sva pitanja iz `pitanja.json` sistemu, u obe varijante.

    AWS_PROFILE=lazar-private evaluation/.venv/bin/python evaluation/run_queries.py --run-id eval-2026-10-05

Trazi podignut GPU i RagSearchStack. Svaki odgovor zavrsava u `query-log`-u
sa zadatim `evalRunId`; lokalno se cuva samo manifest (pitanje -> queryId).

Pitanja idu redom, jedno po jedno, A pa B za isto pitanje: iza sistema je
jedna GPU instanca, a paralelni zahtevi bi merili i red cekanja na njoj.
Prekinut prolaz se nastavlja istom komandom — vec odgovorena pitanja se
preskacu. `--retry-failed` ponovo postavlja samo ona koja nisu uspela.

Poredjenje oblika pretrage (samo pretraga, bez generisanja i bez sudije):

    run_queries.py --run-id ret-2026-11-24-bm25 --retrieval bm25 --retrieval-only

`--retrieval-only` postavlja samo varijantu A: pretraga je u A i B ista.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aws_io  # noqa: E402
from dataset import (RETRIEVAL_MODES, VARIANTS, append_jsonl, latest_by_key,  # noqa: E402
                     load_questions, read_jsonl, run_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=VARIANTS)
    parser.add_argument("--retrieval", default="dense_bm25", choices=RETRIEVAL_MODES)
    parser.add_argument("--retrieval-only", action="store_true",
                        help="samo pretraga, bez generisanja (i samo varijanta A)")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--only", nargs="*", help="samo ova pitanja (npr. A4 H4)")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if args.retrieval_only:
        args.variants = ["A"]

    function_name = aws_io.stack_outputs("RagQueryStack")["QueryFunctionName"]
    manifest_path = os.path.join(run_dir(args.run_id), "manifest.jsonl")
    done = latest_by_key(read_jsonl(manifest_path), "id", "variant")

    questions = load_questions()
    if args.only:
        questions = [q for q in questions if q["id"] in set(args.only)]

    for q in questions:
        for variant in args.variants:
            previous = done.get((q["id"], variant))
            if previous and (not previous.get("error") or not args.retry_failed):
                continue
            started = time.monotonic()
            result = aws_io.invoke_query(function_name, {
                "question": q["pitanje"],
                "variant": variant,
                "retrieval": args.retrieval,
                "k": args.k,
                "evalRunId": args.run_id,
                "retrievalOnly": args.retrieval_only,
            })
            row = {
                "id": q["id"],
                "variant": variant,
                "queryId": result.get("queryId"),
                "statusCode": result.get("statusCode"),
                "seconds": round(time.monotonic() - started, 2),
                "retrieval": args.retrieval,
                "k": args.k,
            }
            if args.retrieval_only:
                row["retrievalOnly"] = True
            # Stara Lambda (pre deploy-a) bi tiho zanemarila oba polja: vratila bi
            # hibrid sa odgovorom, a prolaz bi izgledao kao merenje druge grane.
            if result.get("statusCode") == 200 and (
                    result.get("retrieval") != args.retrieval
                    or bool(result.get("retrievalOnly")) != args.retrieval_only):
                sys.exit("Lambda nije vratila trazeni oblik pretrage — da li je "
                         "RagQueryStack deploy-ovan sa novim kodom?")
            if result.get("statusCode") != 200:
                row["error"] = result.get("error") or "status {}".format(result.get("statusCode"))
            append_jsonl(manifest_path, row)
            print("{:>4} {}  {:>5.1f} s  {}".format(
                q["id"], variant, row["seconds"], row.get("error") or "ok"), flush=True)


if __name__ == "__main__":
    main()
