"""
Metrike pretrage (odeljak 2.5.1 rada): Hit@k, MRR i odziv po dokumentima.
Ciste funkcije, bez ragas-a i bez sudije — racunaju se iz zapisa u
`query-log`-u i iz `pitanja.json`.

Sta je "relevantan" deo:
  - deo iz jednog od dokumenata u kojima je odgovor (`dokumenti`);
  - za pitanja "samo na slici" uz to mora biti deo poreklom od slike — tekst
    istog dokumenta odgovor ne sadrzi, pa ga ne racunamo kao pogodak.

Pretraga je u varijantama A i B ista, pa se metrike racunaju nad A, a B sluzi
kao provera da je pretraga zaista vratila iste delove (`same_retrieval`).
"""

from typing import Any, Dict, List, Optional, Sequence


def is_relevant(ctx: Dict[str, Any], documents: Sequence[str], image_only: bool) -> bool:
    if ctx.get("documentId") not in documents:
        return False
    return ctx.get("chunkType") == "image" if image_only else True


def first_relevant_rank(record: Dict[str, Any]) -> Optional[int]:
    for ctx in sorted(record["contexts"], key=lambda c: c.get("rank") or 0):
        if is_relevant(ctx, record["documents"], record["imageOnly"]):
            return int(ctx["rank"])
    return None


def document_recall(record: Dict[str, Any]) -> float:
    """Udeo dokumenata sa odgovorom koji imaju bar jedan deo medju pronadjenim."""
    found = {c.get("documentId") for c in record["contexts"]}
    wanted = record["documents"]
    return sum(1 for d in wanted if d in found) / len(wanted)


def summarize(records: List[Dict[str, Any]], k: int) -> Dict[str, float]:
    """Hit@k, MRR i prosecan odziv po dokumentima za dati skup zapisa."""
    if not records:
        return {"n": 0, "hit_at_k": float("nan"), "mrr": float("nan"),
                "doc_recall": float("nan")}
    ranks = [first_relevant_rank(r) for r in records]
    hits = [1 if (rank is not None and rank <= k) else 0 for rank in ranks]
    rr = [1.0 / rank if (rank is not None and rank <= k) else 0.0 for rank in ranks]
    return {
        "n": len(records),
        "hit_at_k": sum(hits) / len(records),
        "mrr": sum(rr) / len(records),
        "doc_recall": sum(document_recall(r) for r in records) / len(records),
    }


def chunk_ids(record: Dict[str, Any]) -> List[str]:
    return [c.get("chunkId") for c in sorted(record["contexts"], key=lambda c: c.get("rank") or 0)]


def same_retrieval(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Da li su varijante A i B za isto pitanje dobile iste delove, istim redom."""
    return chunk_ids(a) == chunk_ids(b)
