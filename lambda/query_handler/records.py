"""
Zapis za `query-log`. Ciste funkcije.

`query-log` je DIREKTAN IZVOR PODATAKA ZA RAGAS EVALUACIJU, ne debug log. Zato
cuva sve sto bilo koji sudija moze da trazi — pitanje, tacno one kontekste
koje je generator video, i odgovor — plus sve sto odredjuje uslove merenja:
varijantu, oblik pretrage, k, model, otisak prompta i koje su slike stvarno
poslate. Izbor sudije je jos otvoren (2026-09-26); zapis ne sme od njega
zavisiti.

DynamoDB ne prima Python `float` preko boto3 resource API-ja — trazi
`Decimal`. Konverzija je ovde, na jednom mestu, a ne rasuta po handleru.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence


def to_dynamo(value: Any) -> Any:
    """Rekurzivno: float -> Decimal, a None se izbacuje iz recnika."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        # Preko str-a, ne direktno: Decimal(0.1) nosi binarnu gresku zapisa.
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    return value


def build_log_item(
    query_id: str,
    created_at: str,
    request: Dict[str, Any],
    contexts: Sequence[Dict[str, Any]],
    answer: str,
    attached_images: List[str],
    latencies_ms: Dict[str, float],
    model: str,
    pipeline: str,
    prompt_fingerprint: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Jedan zapis po pitanju.

    `evalRunId` se izostavlja kad ga nema (ne upisuje se kao prazan): GSI
    `byEvalRun` je tada redak i sadrzi samo evaluaciona pitanja, bez rucnih
    proba iz UI-ja.
    """
    item = {
        "queryId": query_id,
        "createdAt": created_at,
        "evalRunId": request.get("evalRunId"),
        "question": request["question"],
        "variant": request["variant"],
        "retrieval": request["retrieval"],
        "k": request["k"],
        "contexts": [
            {
                "rank": c.get("rank"),
                "score": c.get("score"),
                "chunkId": c.get("chunk_id"),
                "chunkType": c.get("chunk_type"),
                "text": c.get("text", ""),
                "imageRef": c.get("image_ref"),
                "documentId": c.get("document_id"),
                "page": c.get("page"),
            }
            for c in contexts
        ],
        "attachedImages": list(attached_images),
        "answer": answer,
        "latencyMs": dict(latencies_ms),
        "model": model,
        "pipeline": pipeline,
        "promptFingerprint": prompt_fingerprint,
        "error": error,
    }
    return to_dynamo(item)
