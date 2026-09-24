"""
IndexChunks — bulk indeksiranje u OpenSearch.

Cita vektorizovane chunkove iz S3 i salje ih u indeks u grupama. I/O-bound
korak: ne dotice GPU, pa je odvojen od EmbedChunks-a i sme da se ponavlja
nezavisno ako indeksiranje padne.

Domen je u VPC-u, pa se saobracaj potpisuje SigV4 identitetom Lambda uloge.
Bez opensearch-py: botocore je vec u runtime-u i nosi potpisivanje, a urllib
HTTP. Time paket ostaje bez zavisnosti i bez Docker build-a.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from bulk import build_bulk_body, failed_items

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
_SESSION = boto3.Session()

DATA_BUCKET = os.environ["DATA_BUCKET"]
REGION = os.environ["AWS_REGION"]

# Endpoint i ime indeksa se citaju iz SSM-a u vreme IZVRSAVANJA, ne iz env
# promenljive popunjene cross-stack export-om. Export bi napravio zavisnost
# koju CloudFormation postuje pri brisanju, pa `cdk destroy RagSearchStack`
# vise ne bi prolazio dok postoji ovaj stack — a rusenje domena tokom pauza je
# razlog zbog kog je on uopste izdvojen.
ENDPOINT_PARAM = os.environ.get("OPENSEARCH_ENDPOINT_PARAM", "/rag/opensearch/endpoint")
INDEX_NAME_PARAM = os.environ.get("INDEX_NAME_PARAM", "/rag/opensearch/index-name")

ssm = boto3.client("ssm")
_cache = {}


def _param(name: str) -> str:
    """Kesirano citanje SSM parametra; kes zivi koliko i topla Lambda."""
    if name not in _cache:
        try:
            _cache[name] = ssm.get_parameter(Name=name)["Parameter"]["Value"]
        except ssm.exceptions.ParameterNotFound:
            raise RuntimeError(
                "SSM parametar {} ne postoji — da li je RagSearchStack "
                "deploy-ovan?".format(name)
            )
    return _cache[name]

# Bulk telo ne sme da bude preveliko: OpenSearch odbija zahteve preko
# http.max_content_length (podrazumevano 100MB), a chunk sa 1024-dimenzionim
# vektorom je oko 20KB. 500 dokumenata je oko 10MB — daleko ispod granice, a
# dovoljno veliko da broj poziva ostane mali.
BULK_SIZE = int(os.environ.get("BULK_SIZE", "500"))


def _signed_post(path: str, body: str) -> Dict[str, Any]:
    url = "https://{}{}".format(_param(ENDPOINT_PARAM), path)
    data = body.encode("utf-8")

    aws_request = AWSRequest(
        method="POST", url=url, data=data,
        headers={"Content-Type": "application/x-ndjson"},
    )
    credentials = _SESSION.get_credentials().get_frozen_credentials()
    SigV4Auth(credentials, "es", REGION).add_auth(aws_request)

    request = urllib.request.Request(
        url, data=data, method="POST", headers=dict(aws_request.headers)
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            "OpenSearch {} : {}".format(error.code, error.read().decode("utf-8")[:500])
        )


def handler(event, _context):
    bucket = event.get("bucket", DATA_BUCKET)
    document_id = event["documentId"]
    key = event["embeddedKey"]

    chunks: List[Dict[str, Any]] = json.loads(
        s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    )

    # Vreme indeksiranja se upisuje ovde, a ne pri ekstrakciji: zanima nas kad
    # je dokument postao pretraziv, jer se po tome razdvajaju evaluacioni prolazi.
    now = datetime.now(timezone.utc).isoformat()
    for chunk in chunks:
        chunk.setdefault("ingested_at", now)

    index_name = _param(INDEX_NAME_PARAM)

    indexed = 0
    failures: List[Dict[str, Any]] = []
    for start in range(0, len(chunks), BULK_SIZE):
        batch = chunks[start : start + BULK_SIZE]
        body = build_bulk_body(batch, index_name)
        if not body:
            continue
        response = _signed_post("/_bulk", body)
        batch_failures = failed_items(response)
        failures.extend(batch_failures)
        indexed += len(batch) - len(batch_failures)

    if failures:
        # Glasno i sa primerima: bulk vraca HTTP 200 i kad pojedinacne stavke
        # ne prodju, pa bi tih neuspeh znacio pola indeksiranog korpusa.
        logger.error("neuspelo %d stavki, prve tri: %s", len(failures), failures[:3])
        raise RuntimeError(
            "indeksiranje nije potpuno: {} od {} stavki nije proslo".format(
                len(failures), len(chunks)
            )
        )

    logger.info("indeksirano %d chunkova u %s", indexed, index_name)
    return {
        "documentId": document_id,
        "indexed": indexed,
        "index": index_name,
    }
