"""
ExtractAndPrepare — prvi korak ingestion toka.

Preuzme dokument iz `raw/`, izvuce elemente, napravi chunkove, slike posalje u
`images/`, a manifest u `manifests/`. Vraca SAMO pokazivace i brojace.

Zasto ne vraca chunkove: Step Functions ima tvrd limit od 256KB na velicinu
stanja. Dokument sa nekoliko stotina chunkova ga probija, a kvar bi se javio
tek na stvarnom korpusu, ne na test dokumentu. Zato `chunks.json` ide u S3 kao
cist JSON niz i cita ga DistributedMap preko ItemReader-a.

Ovo je JEDINI modul u `extract_and_prepare` koji zna za boto3. Pravila
chunkovanja, tabela i imenovanja su u `chunking.py`, `elements.py` i
`naming.py`, pa se testiraju bez AWS-a.
"""

import json
import logging
import os
import tempfile

import boto3

from elements import build_chunks, pending_manifest
from extractor import extract
from naming import document_id_from_key, image_key, manifest_keys

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

DATA_BUCKET = os.environ["DATA_BUCKET"]


def _make_image_sink(bucket: str, document_id: str):
    """
    Pravi `image_sink` koji slike salje u S3 i vraca kljuc kao `image_ref`.

    Brojac je u zatvorenju, pa su imena slika redna i stabilna unutar dokumenta.
    `image_ref` je polje na kome stoji varijanta B ablacije — preko njega
    generator dobija ORIGINALNU sliku, ne samo caption.
    """
    counter = {"n": 0}

    def sink(data: bytes, suffix: str) -> str:
        key = image_key(document_id, counter["n"], suffix)
        counter["n"] += 1
        s3.put_object(Bucket=bucket, Key=key, Body=data)
        return key

    return sink


def handler(event, _context):
    """
    Ulaz (iz Step Functions, poreklom iz EventBridge S3 dogadjaja):
        {"bucket": "...", "key": "raw/dokument.pdf"}

    Izlaz:
        {"documentId", "sourceUri", "chunksKey", "manifestKey", "total", "counts"}
    """
    bucket = event.get("bucket", DATA_BUCKET)
    key = event["key"]

    document_id = document_id_from_key(key)
    source_uri = "s3://{}/{}".format(bucket, key)
    logger.info("ekstrakcija: %s -> document_id=%s", source_uri, document_id)

    # Lambda daje /tmp; preuzimanje je nuzno jer PyMuPDF trazi putanju na disku.
    suffix = os.path.splitext(key)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        local_path = tmp.name
    try:
        s3.download_file(bucket, key, local_path)

        elements = extract(local_path, _make_image_sink(bucket, document_id))
        chunks = build_chunks(elements, document_id, source_uri)
        manifest = pending_manifest(chunks, document_id, source_uri)
    finally:
        if os.path.exists(local_path):
            os.remove(local_path)

    chunks_key, manifest_key = manifest_keys(document_id)

    # CIST niz — bez omotaca, jer ga tako cita DistributedMap.
    s3.put_object(
        Bucket=bucket,
        Key=chunks_key,
        Body=json.dumps(chunks, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
    # Metapodaci odvojeno, za FinalizeIngestion i dijagnostiku.
    s3.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(
            {k: v for k, v in manifest.items() if k != "chunks"}, ensure_ascii=False
        ).encode("utf-8"),
        ContentType="application/json",
    )

    logger.info(
        "pripremljeno %d chunkova (%s)", manifest["total"], manifest["counts"]
    )

    return {
        "documentId": document_id,
        "sourceUri": source_uri,
        "bucket": bucket,
        "chunksKey": chunks_key,
        "manifestKey": manifest_key,
        "total": manifest["total"],
        "counts": manifest["counts"],
    }
