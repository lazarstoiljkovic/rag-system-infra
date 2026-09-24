"""
FinalizeIngestion — upis ishoda u `ingestion-log`.

Poslednji korak toka. Namerno trivijalan i namerno odvojen: ako padne, nista
se ne gubi osim zapisa, a ceo skup koraka pre njega je vec zavrsen.

Uporedjuje broj pripremljenih i broj indeksiranih chunkova. Ta razlika je
jedini automatski znak da je nesto usput tiho otpalo — recimo slika kojoj
captioning nije uspeo, pa je izbacena kao chunk bez teksta.
"""

import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["INGESTION_LOG_TABLE"])

STATUS_OK = "SUCCEEDED"
STATUS_PARTIAL = "PARTIAL"


def handler(event, _context):
    document_id = event["documentId"]
    started_at = event.get("startedAt") or datetime.now(timezone.utc).isoformat()

    prepared = int(event.get("total", 0))
    indexed = int(event.get("indexed", 0))
    skipped = int(event.get("skipped", 0))

    # PARTIAL, a ne SUCCEEDED: dokument JESTE pretraziv, ali nepotpuno. Tiho
    # svodjenje na uspeh bi znacilo da se u evaluaciji ne zna da deo korpusa
    # nikad nije usao u indeks.
    status = STATUS_OK if indexed == prepared else STATUS_PARTIAL

    item = {
        "documentId": document_id,
        "startedAt": started_at,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "sourceUri": event.get("sourceUri"),
        "preparedChunks": prepared,
        "indexedChunks": indexed,
        "skippedChunks": skipped,
        "counts": event.get("counts"),
    }
    table.put_item(Item={k: v for k, v in item.items() if v is not None})

    if status == STATUS_PARTIAL:
        logger.warning(
            "%s: pripremljeno %d, indeksirano %d (preskoceno %d)",
            document_id, prepared, indexed, skipped,
        )
    else:
        logger.info("%s: %d chunkova indeksirano", document_id, indexed)

    return {"documentId": document_id, "status": status,
            "preparedChunks": prepared, "indexedChunks": indexed}
