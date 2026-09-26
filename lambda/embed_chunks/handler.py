"""
EmbedChunks — vektorizacija chunkova, u batch-evima.

Cita chunkove koje je Map state ostavio u S3, salje ih bge-m3 servisu u
grupama i upisuje obogacene chunkove nazad u S3, za IndexChunks.

Sve prolazi kroz ISTI tekstualni model: tekst, tabele serijalizovane u
Markdown i captioni slika. Time je vektorski prostor jedinstven i tekstualan.
Ovo NIJE zajednicka multimodalna vektorizacija teksta i slike.

Kao i ExtractAndPrepare, vraca samo pokazivace — lista vektora od 1024 broja
po chunk-u probila bi limit Step Functions-a od 256KB visestruko.
"""

import json
import logging
import os
from typing import Any, Dict, List

import boto3

from batching import (
    DEFAULT_BATCH_SIZE,
    attach_embeddings,
    chunked,
    drop_empty,
    embeddable_text,
    outputs_from_result_file,
)
from inference import embed, find_inference_ip

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

DATA_BUCKET = os.environ["DATA_BUCKET"]
BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", DEFAULT_BATCH_SIZE))


def _read_json(bucket: str, key: str) -> Any:
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def _load_chunks(bucket: str, key: str) -> List[Dict[str, Any]]:
    """
    Ucitava chunkove iz obicnog niza ili iz izlaza DistributedMap-a.

    DistributedMap ne pise jedan fajl nego manifest koji pokazuje na vise
    `SUCCEEDED_*.json` datoteka, a svaki zapis u njima ima oblik
    `{"Input": ..., "Output": ...}`. Zanima nas `Output`, jer je to chunk posle
    captioning-a (raspakivanje je u `outputs_from_result_file`).
    """
    payload = _read_json(bucket, key)

    if isinstance(payload, list):
        return payload

    results = payload.get("ResultFiles", {}).get("SUCCEEDED", [])
    if not results:
        raise ValueError("iz {} nije moguce procitati chunkove".format(key))

    chunks: List[Dict[str, Any]] = []
    for entry in results:
        chunks.extend(outputs_from_result_file(_read_json(bucket, entry["Key"])))
    return chunks


def handler(event, _context):
    bucket = event.get("bucket", DATA_BUCKET)
    document_id = event["documentId"]
    source_key = event.get("captionedKey") or event["chunksKey"]

    chunks = _load_chunks(bucket, source_key)
    usable = drop_empty(chunks)
    skipped = len(chunks) - len(usable)
    if skipped:
        logger.warning("preskoceno %d chunkova bez teksta", skipped)

    ip = find_inference_ip()

    embedded: List[Dict[str, Any]] = []
    for batch in chunked(usable, BATCH_SIZE):
        vectors = embed(ip, [embeddable_text(c) for c in batch])
        embedded.extend(attach_embeddings(batch, vectors))

    logger.info("vektorizovano %d chunkova u %d poziva",
                len(embedded), (len(usable) + BATCH_SIZE - 1) // BATCH_SIZE)

    out_key = "manifests/{}/embedded.json".format(document_id)
    s3.put_object(
        Bucket=bucket,
        Key=out_key,
        Body=json.dumps(embedded, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )

    return {
        "documentId": document_id,
        "bucket": bucket,
        "embeddedKey": out_key,
        "embedded": len(embedded),
        "skipped": skipped,
    }
