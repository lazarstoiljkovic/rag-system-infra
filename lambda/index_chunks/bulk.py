"""
Sastavljanje tela za OpenSearch `_bulk`. Ciste funkcije, bez mreze.

Bulk format nije obican JSON nego NDJSON: par linija po dokumentu (akcija pa
izvor), svaka linija zaseban JSON, i telo MORA da se zavrsi novim redom.
Izostavljen zavrsni `\\n` je klasican uzrok greske koju OpenSearch prijavi
nejasno, pa je ovde zakljucan testom.
"""

import json
from typing import Any, Dict, Iterable, List, Sequence

# Polja koja se ne indeksiraju: interna, ili vec sadrzana u drugim poljima.
_SKIP = ("bucket",)


def to_document(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chunk -> dokument kakav ocekuje sema indeksa.

    `image_ref` se prenosi i kad je None, da polje postoji u svakom dokumentu.
    Na njemu stoji varijanta B ablacije: preko njega generator dobija originalnu
    sliku, ne samo caption.
    """
    return {
        "text": chunk.get("text", ""),
        "dense_vector": chunk["dense_vector"],
        "sparse_weights": chunk.get("sparse_weights") or {},
        "image_ref": chunk.get("image_ref"),
        "chunk_type": chunk.get("chunk_type"),
        "document_id": chunk.get("document_id"),
        "chunk_id": chunk.get("chunk_id"),
        "source_uri": chunk.get("source_uri"),
        "page": chunk.get("page"),
        "ingested_at": chunk.get("ingested_at"),
    }


def build_bulk_body(chunks: Sequence[Dict[str, Any]], index: str) -> str:
    """
    NDJSON za `_bulk`, sa `index` akcijom i DETERMINISTICKIM `_id`.

    `_id` je `chunk_id`, pa ponovni ingestion istog dokumenta PREPISUJE
    postojece dokumente umesto da pravi duplikate. Bez toga bi svako ponovno
    pokretanje udvostrucavalo korpus, a merenja retrievala postala besmislena.
    """
    lines: List[str] = []
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        if not chunk_id:
            raise ValueError("chunk bez chunk_id ne moze u indeks: {}".format(chunk))
        lines.append(json.dumps({"index": {"_index": index, "_id": chunk_id}}))
        lines.append(json.dumps(to_document(chunk), ensure_ascii=False))
    if not lines:
        return ""
    # Zavrsni novi red je obavezan.
    return "\n".join(lines) + "\n"


def failed_items(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Izvlaci stavke koje nisu uspele iz odgovora na `_bulk`.

    OpenSearch na bulk vraca HTTP 200 i kad pojedinacni dokumenti ne prodju —
    greska je u telu, po stavci. Ko gleda samo statusni kod, indeksira pola
    korpusa i ne primeti.
    """
    if not response.get("errors"):
        return []
    failures = []
    for item in response.get("items", []):
        for _action, result in item.items():
            if result.get("status", 200) >= 300:
                failures.append(
                    {"_id": result.get("_id"), "status": result.get("status"),
                     "error": result.get("error")}
                )
    return failures
