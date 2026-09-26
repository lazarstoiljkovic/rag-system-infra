"""
Citanje i provera zahteva, i oblik HTTP odgovora. Ciste funkcije.

Zahtev stize na dva nacina, i oba se svode na isti recnik:

  API Gateway (proxy integracija)  telo je JSON STRING u `body`, eventualno
                                   base64 kodiran
  direktan Lambda poziv            dogadjaj je vec sam recnik zahteva

Drugi put postoji zbog evaluacije: batch skripta zove Lambdu direktno i time
zaobilazi tvrd limit API Gateway-a od 29s. Rezultat je isti zapis u
`query-log`-u, pa za RAGAS nije bitno kojim je putem pitanje stiglo.
"""

import base64
import json
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from prompting import VARIANT_A, VARIANTS
from retrieval import DENSE_BM25, MODES

MAX_QUESTION_CHARS = 2000
DEFAULT_K = 5
MAX_K = 20

# evalRunId ulazi u GSI `byEvalRun` i u imena izvestaja, pa je skup znakova
# namerno uzak.
_EVAL_RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class BadRequest(ValueError):
    """Zahtev nije ispravan; poruka ide klijentu uz HTTP 400."""


def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    if "body" not in event and "requestContext" not in event:
        return event  # direktan poziv

    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise BadRequest("telo zahteva nije ispravan JSON: {}".format(error.msg))
    if not isinstance(body, dict):
        raise BadRequest("telo zahteva mora biti JSON objekat")
    return body


def parse_request(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Vraca `{question, variant, retrieval, k, evalRunId}` ili dize BadRequest.

    Podrazumevano: varijanta A, osnovna pretraga (dense_bm25), k = 5. Varijanta
    i oblik pretrage se ipak uvek upisuju u `query-log`, pa se iz zapisa uvek
    zna sta je bilo, cak i kad klijent to nije poslao.
    """
    body = _body(event)

    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        raise BadRequest("polje 'question' je obavezno i ne sme biti prazno")
    question = question.strip()
    if len(question) > MAX_QUESTION_CHARS:
        raise BadRequest("pitanje je duze od {} znakova".format(MAX_QUESTION_CHARS))

    variant = str(body.get("variant", VARIANT_A)).strip().upper()
    if variant not in VARIANTS:
        raise BadRequest("'variant' mora biti jedno od: {}".format(", ".join(VARIANTS)))

    retrieval = str(body.get("retrieval", DENSE_BM25)).strip().lower()
    if retrieval not in MODES:
        raise BadRequest("'retrieval' mora biti jedno od: {}".format(", ".join(MODES)))

    k = body.get("k", DEFAULT_K)
    # bool je podklasa int-a u Python-u; `true` ne sme proci kao k = 1.
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise BadRequest("'k' mora biti ceo broj od 1 do {}".format(MAX_K))

    eval_run_id = body.get("evalRunId")
    if eval_run_id is not None:
        if not isinstance(eval_run_id, str) or not _EVAL_RUN_ID.match(eval_run_id):
            raise BadRequest("'evalRunId' sme imati samo slova, cifre, '.', '_' i '-' "
                             "(do 128 znakova)")

    return {
        "question": question,
        "variant": variant,
        "retrieval": retrieval,
        "k": k,
        "evalRunId": eval_run_id,
    }


# Koliko teksta izvora ide u HTTP odgovor. Ceo tekst ostaje u query-log-u;
# UI-ju treba dovoljno da se vidi zasto je izvor izabran.
SNIPPET_CHARS = 600


def public_sources(
    contexts: Sequence[Dict[str, Any]],
    attached_images: Sequence[str],
    presign: Callable[[str], Optional[str]],
) -> List[Dict[str, Any]]:
    """
    Izvori za HTTP odgovor (UI), u redosledu ranga.

    `imageUrl` je privremeni (presigned) link ka ORIGINALNOJ slici, da UI moze
    da prikaze sliku pored njenog captiona — bucket sa podacima ostaje
    privatan. `sentToGenerator` kaze da li je generator stvarno video sliku:
    u A nikad, u B najvise cetiri po rangu.
    """
    attached = set(attached_images)
    out = []
    for c in contexts:
        text = c.get("text") or ""
        ref = c.get("image_ref")
        out.append({
            "rank": c.get("rank"),
            "chunkId": c.get("chunk_id"),
            "chunkType": c.get("chunk_type"),
            "documentId": c.get("document_id"),
            "page": c.get("page"),
            "score": c.get("score"),
            "text": text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS] + "...",
            "imageRef": ref,
            "imageUrl": presign(ref) if ref else None,
            "sentToGenerator": bool(ref) and ref in attached,
        })
    return out


def http_response(status: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Odgovor u obliku koji ocekuje API Gateway proxy integracija."""
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            # UI iz faze 6 je staticka S3 stranica na drugom domenu.
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }
