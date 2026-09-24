"""
CaptionChunk — opisivanje slika VLM-om.

Poziva se iz Map state-a, po chunk-u, i SAMO za `chunk_type == "image"`.
Tekstualni i tabelarni chunkovi prolaze bez izmene: tabele su vec
deterministicki serijalizovane u Markdown, pa bi VLM poziv nad njima bio
trosak GPU vremena za losiji rezultat.

Dva poziva po slici: prvo kratka klasifikacija (dijagram ili grafikon), pa
specijalizovani prompt. Jedan opsti prompt bio bi jeftiniji, ali specifikacija
trazi dva razlicita — i s razlogom, videti `prompts.py`.

`image_ref` se NE MENJA i ostaje na chunk-u. Caption popunjava `text`, ali
original mora ostati dohvatljiv, jer varijanta B ablacije salje generatoru i
sliku, ne samo opis.
"""

import logging
import os

import boto3

from inference import chat_completion, find_inference_ip, image_as_data_url
from prompts import CLASSIFY_PROMPT, classify, prompt_for

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

DATA_BUCKET = os.environ["DATA_BUCKET"]

_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


def _content_type(key: str) -> str:
    return _CONTENT_TYPES.get(key.rsplit(".", 1)[-1].lower(), "image/png")


def handler(event, _context):
    chunk = event.get("chunk", event)

    if chunk.get("chunk_type") != "image":
        # Odbrana, ne ocekivan put: grananje radi Choice state u Step Functions.
        return chunk

    image_ref = chunk.get("image_ref")
    if not image_ref:
        raise ValueError("chunk tipa image nema image_ref: {}".format(chunk.get("chunk_id")))

    bucket = chunk.get("bucket", DATA_BUCKET)
    data = s3.get_object(Bucket=bucket, Key=image_ref)["Body"].read()
    data_url = image_as_data_url(data, _content_type(image_ref))

    ip = find_inference_ip()

    def ask(prompt: str, max_tokens: int) -> str:
        return chat_completion(
            ip,
            [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
            max_tokens=max_tokens,
        )

    # Klasifikacija je kratka namerno: treba jedna rec, ne obrazlozenje.
    kind = classify(ask(CLASSIFY_PROMPT, max_tokens=16))
    caption = ask(prompt_for(kind), max_tokens=768).strip()

    logger.info("caption za %s (%s): %d znakova", chunk.get("chunk_id"), kind, len(caption))

    result = dict(chunk)
    result["text"] = caption
    # Vrsta se cuva kao metapodatak: pri analizi rezultata treba moci razdvojiti
    # greske nad dijagramima od gresaka nad grafikonima.
    result["image_kind"] = kind
    return result
