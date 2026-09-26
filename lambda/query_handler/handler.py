"""
QueryHandler — sinhroni put pitanje -> odgovor.

  embedding pitanja (bge-m3) -> hibridna pretraga (OpenSearch) ->
  prompt (varijanta A ili B) -> VLM (Qwen2.5-VL) -> upis u `query-log` -> odgovor

JEDNA Lambda, bez Step Functions: unutar jednog upita nema grananja ni
paralelizma, pa bi orkestracija bila cist overhead. Asimetrija u odnosu na
ingestion je namerna.

Sva pravila (oblik upita, prompt A/B, provera zahteva, oblik zapisa) su u
`retrieval.py`, `prompting.py`, `request.py` i `records.py`, i testiraju se
bez AWS-a. Ovde je samo spajanje sa mrezom.

Neuspeh posle provere zahteva se TAKODJE upisuje u `query-log`, sa greskom.
Pitanje na koje sistem nije odgovorio je podatak za evaluaciju, ne sum — bez
njega bi procenat uspesnih odgovora izgledao bolje nego sto jeste.

Vremenski budzet: API Gateway prekida posle 29s (tvrd limit). Poziv VLM-u
dobija ono sto ostane do isteka Lambde, uz rezervu za upis u log.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3
from botocore.auth import SigV4Auth
from botocore.config import Config
from botocore.awsrequest import AWSRequest

from inference import (
    InferenceUnavailable,
    chat_completion,
    embed,
    find_inference_ip,
    image_as_data_url,
)
from prompting import build_messages, images_to_attach, prompt_fingerprint
from records import build_log_item
from request import BadRequest, http_response, parse_request, public_sources
from retrieval import DENSE_BM25, DENSE_BM25_SPARSE, build_search_body, parse_hits

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
# Zaseban klijent za presigned linkove: eksplicitno SigV4 i regionalni
# virtual-host oblik adrese, da link radi iz pregledaca bez preusmeravanja.
# Potpisivanje je lokalno racunanje, bez ijednog mreznog poziva.
_presigner = boto3.client("s3", region_name=os.environ["AWS_REGION"],
                          config=Config(signature_version="s3v4",
                                        s3={"addressing_style": "virtual"}))
IMAGE_URL_TTL_S = 900
ssm = boto3.client("ssm")
dynamodb = boto3.resource("dynamodb")
_SESSION = boto3.Session()

DATA_BUCKET = os.environ["DATA_BUCKET"]
REGION = os.environ["AWS_REGION"]
QUERY_LOG = dynamodb.Table(os.environ["QUERY_LOG_TABLE"])
ENDPOINT_PARAM = os.environ.get("OPENSEARCH_ENDPOINT_PARAM", "/rag/opensearch/endpoint")
INDEX_NAME_PARAM = os.environ.get("INDEX_NAME_PARAM", "/rag/opensearch/index-name")
PIPELINES = {
    DENSE_BM25: os.environ.get("PIPELINE_DENSE_BM25", "rag-hybrid-dense-bm25"),
    DENSE_BM25_SPARSE: os.environ.get("PIPELINE_DENSE_BM25_SPARSE",
                                      "rag-hybrid-dense-bm25-sparse"),
}
MODEL = os.environ.get("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ")
MAX_ANSWER_TOKENS = int(os.environ.get("MAX_ANSWER_TOKENS", "512"))

# Rezerva do isteka Lambde, za upis u log i povratak odgovora.
_RESERVE_S = 3

_CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                  "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}
_cache: Dict[str, str] = {}


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


def _search(body: Dict[str, Any], pipeline: str) -> Dict[str, Any]:
    """SigV4-potpisan `_search` ka domenu u VPC-u, sa izabranim pipeline-om."""
    url = "https://{}/{}/_search?search_pipeline={}".format(
        _param(ENDPOINT_PARAM), _param(INDEX_NAME_PARAM), pipeline)
    data = json.dumps(body).encode("utf-8")

    aws_request = AWSRequest(method="POST", url=url, data=data,
                             headers={"Content-Type": "application/json"})
    credentials = _SESSION.get_credentials().get_frozen_credentials()
    SigV4Auth(credentials, "es", REGION).add_auth(aws_request)

    request = urllib.request.Request(url, data=data, method="POST",
                                     headers=dict(aws_request.headers))
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError("OpenSearch {} : {}".format(
            error.code, error.read().decode("utf-8")[:500]))


def _load_images(refs: List[str]) -> Dict[str, str]:
    """Originalne slike iz S3, kao data URL-ovi — samo za varijantu B."""
    urls = {}
    for ref in refs:
        data = s3.get_object(Bucket=DATA_BUCKET, Key=ref)["Body"].read()
        content_type = _CONTENT_TYPES.get(ref.rsplit(".", 1)[-1].lower(), "image/png")
        urls[ref] = image_as_data_url(data, content_type)
    return urls


def _presign(ref: str) -> str:
    return _presigner.generate_presigned_url(
        "get_object", Params={"Bucket": DATA_BUCKET, "Key": ref},
        ExpiresIn=IMAGE_URL_TTL_S)


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def handler(event, context):
    try:
        req = parse_request(event)
    except BadRequest as error:
        return http_response(400, {"error": str(error)})

    query_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    pipeline = PIPELINES[req["retrieval"]]
    latencies: Dict[str, float] = {}
    contexts: List[Dict[str, Any]] = []
    attached: List[str] = []
    answer = ""
    error_text = None
    status = 200
    total_start = time.monotonic()

    try:
        ip = find_inference_ip()

        start = time.monotonic()
        vector = embed(ip, [req["question"]], timeout=10)[0]
        latencies["embed"] = _elapsed_ms(start)

        start = time.monotonic()
        body = build_search_body(req["question"], vector["dense"], req["k"],
                                 req["retrieval"], vector.get("sparse"))
        contexts = parse_hits(_search(body, pipeline))
        latencies["search"] = _elapsed_ms(start)

        start = time.monotonic()
        image_urls = _load_images(images_to_attach(contexts, req["variant"]))
        messages, attached = build_messages(req["question"], contexts,
                                            req["variant"], image_urls)
        latencies["images"] = _elapsed_ms(start)

        start = time.monotonic()
        remaining_s = context.get_remaining_time_in_millis() / 1000 - _RESERVE_S
        answer = chat_completion(ip, messages, max_tokens=MAX_ANSWER_TOKENS,
                                 timeout=max(5, int(remaining_s))).strip()
        latencies["generate"] = _elapsed_ms(start)

    except InferenceUnavailable as error:
        status, error_text = 503, str(error)
    except Exception as error:  # noqa: BLE001 - i neuspeh ide u query-log
        logger.exception("upit %s nije uspeo", query_id)
        status, error_text = 500, "{}: {}".format(type(error).__name__, error)

    latencies["total"] = _elapsed_ms(total_start)

    QUERY_LOG.put_item(Item=build_log_item(
        query_id, created_at, req, contexts, answer, attached, latencies,
        MODEL, pipeline, prompt_fingerprint(), error_text,
    ))
    logger.info("upit %s: varijanta=%s pretraga=%s status=%s latencija=%s",
                query_id, req["variant"], req["retrieval"], status, latencies)

    payload = {
        "queryId": query_id,
        "variant": req["variant"],
        "retrieval": req["retrieval"],
        "latencyMs": latencies,
    }
    if error_text:
        payload["error"] = error_text
        return http_response(status, payload)

    payload.update({
        "answer": answer,
        "attachedImages": attached,
        "sources": public_sources(contexts, attached, _presign),
    })
    return http_response(200, payload)
