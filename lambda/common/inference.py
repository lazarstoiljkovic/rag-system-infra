"""
Pronalazenje privatno hostovane inference instance i pozivi ka njoj.

Deljeno izmedju CaptionChunk, EmbedChunks i QueryHandler. Ide kao Lambda Layer,
ne kao kopija u svakom paketu — tri kopije istog klijenta bi se razisle cim se
promeni oblik odgovora servisa.

Bez ALB-a i bez Parameter Store-a: instanca se nalazi preko `ec2:DescribeInstances`
filtrirano po tagu. Za jednu GPU instancu ALB nema sta da balansira, a kosta
vise od nje same u satima kad je ugasena.
"""

import base64
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Dict, List, Optional

import boto3

logger = logging.getLogger()

INFERENCE_TAG_NAME = os.environ.get("INFERENCE_TAG_NAME", "vllm-server")
VLM_PORT = int(os.environ.get("VLM_PORT", "8000"))
EMBEDDING_PORT = int(os.environ.get("EMBEDDING_PORT", "8001"))

ec2 = boto3.client("ec2")


class InferenceUnavailable(RuntimeError):
    """GPU instanca ne postoji ili jos nije spremna."""


def find_inference_ip() -> str:
    """
    Privatna IP adresa instance koja je STVARNO spremna.

    Trazi se i tag `vllm-status=ready`, ne samo stanje `running`. Ucitavanje 7B
    modela u VRAM traje desetine sekundi do par minuta, a prvo dizanje jos i
    skida tezine — instanca u stanju "running" zato ne znaci da servis odgovara.
    Bez ove provere Lambda dobija connection refused i tok pada bez jasnog
    razloga.

    Koristi se PRIVATNA adresa: saobracaj ostaje unutar VPC-a, a security group
    ionako pusta samo Lambda SG.
    """
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [INFERENCE_TAG_NAME]},
            {"Name": "tag:vllm-status", "Values": ["ready"]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            ip = instance.get("PrivateIpAddress")
            if ip:
                logger.info("inference instanca: %s (%s)", instance["InstanceId"], ip)
                return ip

    raise InferenceUnavailable(
        "nema instance sa tagom Name={} i vllm-status=ready — "
        "da li je ASG podignut na 1 i da li je bootstrap zavrsen?".format(
            INFERENCE_TAG_NAME
        )
    )


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:500]
        raise RuntimeError("HTTP {} sa {}: {}".format(error.code, url, body))


def chat_completion(
    ip: str,
    messages: List[dict],
    max_tokens: int = 512,
    temperature: float = 0.0,
    timeout: int = 120,
) -> str:
    """
    Poziv ka vLLM-u (OpenAI-kompatibilan API).

    `temperature=0.0` podrazumevano i namerno: captioni i odgovori moraju biti
    ponovljivi, inace se dva prolaza RAGAS evaluacije ne mogu porediti.
    """
    payload = {
        "model": os.environ.get("VLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = "http://{}:{}/v1/chat/completions".format(ip, VLM_PORT)
    result = _post_json(url, payload, timeout)
    return result["choices"][0]["message"]["content"]


def embed(ip: str, texts: List[str], timeout: int = 120) -> List[Dict]:
    """
    Batch embedding preko `/embed` — vraca i guste vektore i leksicke tezine.

    Namerno NIJE `/v1/embeddings`: taj endpoint daje samo guste vektore, a sema
    indeksa ima i `sparse_weights`.

    Poziva se JEDNOM za ceo batch, ne po chunk-u. Rezija HTTP poziva i ucitavanja
    modela po pozivu bi inace nadmasila samo racunanje.
    """
    url = "http://{}:{}/embed".format(ip, EMBEDDING_PORT)
    result = _post_json(url, {"input": texts}, timeout)
    return result["data"]


def image_as_data_url(data: bytes, content_type: str = "image/png") -> str:
    """Slika u data URL, kako ga ocekuje OpenAI-kompatibilan `image_url`."""
    return "data:{};base64,{}".format(
        content_type, base64.b64encode(data).decode("ascii")
    )
