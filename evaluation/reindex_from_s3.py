"""
Puni indeks iz vec vektorizovanih delova u S3, bez ponovnog ingestion-a.

    AWS_PROFILE=lazar-private evaluation/.venv/bin/python evaluation/reindex_from_s3.py --dry-run
    AWS_PROFILE=lazar-private evaluation/.venv/bin/python evaluation/reindex_from_s3.py

Svaki ingestion ostavlja `manifests/<documentId>/embedded.json`: delove sa
opisima slika, gustim vektorima i retkim tezinama, tacno onako kako su otisli
u indeks. Kad se RagSearchStack srusi i ponovo podigne, indeks je prazan. Ova
skripta poziva IndexChunks direktno, dokument po dokument, i vraca indeks
kakav je bio: bez VLM-a, pa i bez ponovnog opisivanja slika, koje bi dalo malo
drugacije opise i time drugi indeks. Merenja nad tako vracenim indeksom su
uporediva sa merenjima pre rusenja.

Dokumenti se uzimaju iz `corpus/demo/dokumenti/`, a ne iz svega sto je u
`manifests/`: tamo su i ostaci starog korpusa (Vranac, Kestrel, test PDF), koji
ne smeju u indeks.

Puniti samo SVEZE podignut domen. `_id` je `chunk_id`, pa ponovljeno pokretanje
prepisuje iste dokumente, ali ne brise one koji vec stoje u indeksu, a nisu iz
korpusa.

`--dry-run` samo proverava S3 (radi i dok je RagSearchStack srusen).
"""

import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "lambda", "extract_and_prepare"))

import aws_io  # noqa: E402
from naming import MANIFEST_PREFIX, document_id_from_key  # noqa: E402

CORPUS_DIR = os.path.join(ROOT, "corpus", "demo", "dokumenti")


def corpus_document_ids():
    names = sorted(n for n in os.listdir(CORPUS_DIR) if n.lower().endswith((".pdf", ".docx")))
    return [document_id_from_key("raw/" + n) for n in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--dry-run", action="store_true", help="samo provera S3, bez indeksiranja")
    args = parser.parse_args()

    bucket = aws_io.stack_outputs("RagStorageStack")["DataBucketName"]
    s3 = aws_io.s3_client()

    plan = []
    types = collections.Counter()
    dates = collections.Counter()
    for document_id in corpus_document_ids():
        key = "{}{}/embedded.json".format(MANIFEST_PREFIX, document_id)
        obj = s3.get_object(Bucket=bucket, Key=key)
        chunks = json.loads(obj["Body"].read())
        missing = [c.get("chunk_id") for c in chunks if not c.get("dense_vector")]
        if missing:
            sys.exit("{}: delovi bez vektora: {}".format(document_id, missing[:3]))
        types.update(c.get("chunk_type") for c in chunks)
        day = obj["LastModified"].date().isoformat()
        dates[day] += 1
        plan.append((document_id, key, len(chunks)))
        print("{:32} {:3} delova  ({})".format(document_id, len(chunks), day))

    total = sum(n for _, _, n in plan)
    print("\n{} dokumenata, {} delova: {}".format(
        len(plan), total, ", ".join("{} {}".format(n, t) for t, n in sorted(types.items()))))
    if len(dates) > 1:
        # Delovi iz razlicitih ingestion-a znace mesavinu opisa iz razlicitih
        # prolaza; to nije indeks ni jednog merenja.
        print("PAZNJA: embedded.json su iz razlicitih dana: {}".format(dict(dates)))
    if args.dry_run:
        return

    function_name = aws_io.stack_function_name("RagIngestionStack", "IndexChunks")
    indexed = 0
    for document_id, key, expected in plan:
        result = aws_io.invoke_json(function_name, {"documentId": document_id, "embeddedKey": key})
        indexed += result["indexed"]
        status = "ok" if result["indexed"] == expected else "OCEKIVANO {}".format(expected)
        print("{:32} {:3} indeksirano  {}".format(document_id, result["indexed"], status), flush=True)

    print("\nindeksirano {} od {} delova".format(indexed, total))
    if indexed != total:
        sys.exit("indeks nije potpun")


if __name__ == "__main__":
    main()
