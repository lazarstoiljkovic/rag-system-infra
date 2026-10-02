"""
Preuzima zapise jednog prolaza iz `query-log`-a u lokalni `log.jsonl`.

    AWS_PROFILE=lazar-private evaluation/.venv/bin/python evaluation/fetch_log.py --run-id eval-2026-10-05

Posle ovoga ocenjivanje i izvestaj rade iskljucivo nad lokalnim fajlovima,
pa se mogu ponavljati bez AWS-a (osim originalnih slika za sudiju, koje se
preuzimaju jednom i kesiraju).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aws_io  # noqa: E402
from dataset import run_dir  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    outputs = aws_io.stack_outputs("RagStorageStack")
    items = aws_io.query_log_items(outputs["QueryLogTableName"], args.run_id)
    path = os.path.join(run_dir(args.run_id), "log.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in sorted(items, key=lambda i: i["createdAt"]):
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print("{} zapisa -> {}".format(len(items), os.path.relpath(path)))


if __name__ == "__main__":
    main()
