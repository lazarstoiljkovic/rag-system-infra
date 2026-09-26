"""
Kreiranje indeksa sa hibridnom semom nad privatno hostovanim OpenSearch domenom.

Pokrece se kao CloudFormation custom resource, dakle pri svakom deploy-u
search-stack-a. Namerno NIJE deo ingestion Lambdi: sema indeksa je deo
infrastrukture, ne deo obrade podataka, pa treba da nastane zajedno sa domenom.

Zasto bez opensearch-py i requests-a: ova Lambda zivi u VPC-u bez NAT-a i mora
da ostane bez ijedne eksterne zavisnosti, da ne bi trazila Docker build. botocore
je vec u runtime-u i nosi SigV4 potpisivanje, a urllib nosi HTTP. To je dovoljno.

VAZNO (mrezni preduslov): odgovor CloudFormation-u je PUT na presigned S3 URL.
Lambda u VPC-u bez NAT-a do njega stize iskljucivo preko S3 gateway endpoint-a
iz network-stack-a. Bez tog endpoint-a deploy ne pukne odmah nego visi do
timeout-a, sto je znatno teze dijagnostikovati.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from pipelines import all_pipelines

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ["AWS_REGION"]
ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"]
INDEX_NAME = os.environ["INDEX_NAME"]
VECTOR_DIM = int(os.environ["VECTOR_DIM"])

_SESSION = boto3.Session()


def _index_definition() -> dict:
    """
    Hibridna sema: BM25 nad `text`, kNN nad `dense_vector`, `sparse_weights`
    za leksicke tezine iz bge-m3, plus metapodaci.

    `image_ref` je kljucno polje ablacije: kad chunk potice od slike, cuva
    pokazivac na original u S3. Varijanta B ga koristi da generatoru prosledi
    i samu sliku, a ne samo caption. Bez njega bi varijanta B bila neizvodljiva.

    Svi chunkovi (tekst, tabela, caption slike) idu kroz isti tekstualni model,
    pa je `dense_vector` jedinstven vektorski prostor. Ovo NIJE zajednicka
    multimodalna vektorizacija.
    """
    return {
        "settings": {
            "index": {
                "knn": True,
                "number_of_shards": 1,
                # Jedan node, pa replika ne bi imala gde da se rasporedi i
                # klaster bi trajno stajao u "yellow" stanju.
                "number_of_replicas": 0,
            }
        },
        "mappings": {
            "properties": {
                # BM25 grana hibridne pretrage.
                "text": {"type": "text"},
                # Gusta grana: bge-m3 daje 1024 dimenzije, metrika kosinusna.
                # Engine lucene, a ne nmslib: nmslib je deprecated, a lucene
                # podrzava filtriranje po metapodacima uz kNN.
                "dense_vector": {
                    "type": "knn_vector",
                    "dimension": VECTOR_DIM,
                    "method": {
                        "name": "hnsw",
                        "engine": "lucene",
                        "space_type": "cosinesimil",
                        "parameters": {"ef_construction": 128, "m": 16},
                    },
                },
                # Leksicke tezine iz bge-m3 (token -> tezina).
                "sparse_weights": {"type": "rank_features"},
                # Metapodaci i trag do originala.
                "image_ref": {"type": "keyword"},
                "chunk_type": {"type": "keyword"},   # text | table | image
                "document_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "source_uri": {"type": "keyword"},
                "page": {"type": "integer"},
                "ingested_at": {"type": "date"},
            }
        },
    }


# Domen prijavljen kao CREATE_COMPLETE ne znaci da njegov endpoint vec prima
# TLS konekcije. 2026-09-26 je prvi zahtev 35 s posle kreiranja pao sa
# "SSL: UNEXPECTED_EOF_WHILE_READING", CloudFormation je vratio ceo stack
# unazad — a brisanje domena traje 15-45 min. Zato se mrezne greske ponavljaju
# sa rastucim razmakom, ukupno do ~4 minuta (Lambda ima 5).
_RETRY_DELAYS_S = (5, 10, 20, 30, 45, 60, 60)


def _signed_request(method: str, path: str, body: dict | None = None):
    """Kao `_signed_request_once`, ali ponavlja pri mreznim i TLS greskama."""
    for attempt, delay in enumerate(_RETRY_DELAYS_S + (None,), start=1):
        try:
            return _signed_request_once(method, path, body)
        # OSError pokriva URLError, ssl.SSLError (i kad pukne tek pri citanju
        # odgovora), ConnectionError i TimeoutError. HTTP greske (4xx/5xx) ovde
        # ne stizu — `_signed_request_once` ih vraca kao (status, telo).
        except OSError as error:
            if delay is None:
                raise
            logger.warning("Domen jos ne odgovara (%s, pokusaj %d), cekam %d s.",
                           error, attempt, delay)
            time.sleep(delay)


def _signed_request_once(method: str, path: str, body: dict | None = None):
    """Potpisan SigV4 zahtev ka domenu. Vraca (status, telo)."""
    url = f"https://{ENDPOINT}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None

    aws_request = AWSRequest(
        method=method,
        url=url,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    credentials = _SESSION.get_credentials().get_frozen_credentials()
    SigV4Auth(credentials, "es", REGION).add_auth(aws_request)

    http_request = urllib.request.Request(
        url, data=data, method=method, headers=dict(aws_request.headers)
    )
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def _create_index() -> str:
    """Idempotentno: ako indeks vec postoji, ostavlja ga netaknutim."""
    status, _ = _signed_request("HEAD", f"/{INDEX_NAME}")
    if status == 200:
        logger.info("Indeks %s vec postoji, preskacem kreiranje.", INDEX_NAME)
        return f"{INDEX_NAME} (postojao)"

    status, payload = _signed_request("PUT", f"/{INDEX_NAME}", _index_definition())
    if status not in (200, 201):
        raise RuntimeError(f"Kreiranje indeksa nije uspelo ({status}): {payload}")

    logger.info("Indeks %s kreiran.", INDEX_NAME)
    return f"{INDEX_NAME} (kreiran)"


def _put_search_pipelines() -> str:
    """
    Search pipeline-i za hibridnu pretragu (vidi `pipelines.py`).

    `PUT` nad pipeline-om je idempotentan — prepisuje postojeci — pa se pri
    svakom deploy-u search-stack-a pipeline-i dovode u stanje iz koda. Za
    razliku od indeksa, ovde nema podataka koji bi se izgubili.
    """
    names = []
    for name, body in all_pipelines().items():
        status, payload = _signed_request("PUT", f"/_search/pipeline/{name}", body)
        if status not in (200, 201):
            raise RuntimeError(f"Pipeline {name} nije prihvacen ({status}): {payload}")
        status, payload = _signed_request("GET", f"/_search/pipeline/{name}")
        logger.info("Prihvacen pipeline %s (%s): %s", name, status, payload)
        names.append(name)
    return ", ".join(names)


def _log_effective_state() -> None:
    """
    Cita nazad ono sto je OpenSearch STVARNO prihvatio i upisuje u log.

    Nije kozmetika: domen je u VPC-u i nedostupan sa developerove masine, pa je
    ovaj log jedini nacin da se potvrdi da su `knn_vector` sa lucene engine-om
    i `rank_features` prosli bas onako kako su poslati. Poslat mapping i
    prihvacen mapping ne moraju biti isti — OpenSearch tise popunjava
    podrazumevane vrednosti.
    """
    status, payload = _signed_request("GET", f"/{INDEX_NAME}/_mapping")
    logger.info("Prihvaceni mapping (%s): %s", status, payload)

    status, payload = _signed_request("GET", f"/{INDEX_NAME}/_settings")
    logger.info("Prihvacena podesavanja (%s): %s", status, payload)

    status, payload = _signed_request("GET", "/_cluster/health")
    logger.info("Zdravlje klastera (%s): %s", status, payload)


def _send_response(event, context, status: str, reason: str, physical_id: str):
    """CloudFormation custom resource protokol: PUT na presigned S3 URL."""
    body = json.dumps(
        {
            "Status": status,
            "Reason": f"{reason} Log: {context.log_stream_name}",
            "PhysicalResourceId": physical_id,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": {"IndexName": INDEX_NAME},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        event["ResponseURL"], data=body, method="PUT",
        headers={"Content-Type": "", "Content-Length": str(len(body))},
    )
    with urllib.request.urlopen(request, timeout=30):
        logger.info("CloudFormation obavesten: %s", status)


def handler(event, context):
    logger.info("Zahtev: %s", event["RequestType"])
    physical_id = event.get("PhysicalResourceId", f"index-{INDEX_NAME}")

    try:
        if event["RequestType"] in ("Create", "Update"):
            detail = _create_index()
            detail += "; pipeline-i: " + _put_search_pipelines()
            _log_effective_state()
        else:
            # Delete: indeks se NE brise. Ako neko srusi stack da ustedi novac,
            # a domen ostane, brisanje indeksa bi tiho pojelo ceo indeksirani
            # korpus. Indeks jeste izveden podatak, ali njegova regeneracija
            # kosta GPU sate za captioning.
            detail = "indeks namerno zadrzan"

        _send_response(event, context, "SUCCESS", detail, physical_id)
    except Exception as error:  # noqa: BLE001 - greska mora stici do CFN-a
        logger.exception("Neuspeh pri obradi custom resource-a")
        _send_response(event, context, "FAILED", str(error), physical_id)
