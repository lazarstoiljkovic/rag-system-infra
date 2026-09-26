"""
Sklapanje hibridnog upita i citanje rezultata. Ciste funkcije, bez mreze.

Dva oblika pretrage (odluka 2026-09-26):

  dense_bm25          OSNOVNA, kako je specificirano: BM25 nad `text` + kNN
                      nad `dense_vector`.
  dense_bm25_sparse   SEKUNDARNI EKSPERIMENT: isto, plus treci podupit nad
                      `sparse_weights` (leksicke tezine iz bge-m3).

Ovaj eksperiment je o RETRIEVAL-u i nezavisan je od glavne ablacije A/B, koja
je o generatoru. Zato je oblik pretrage zaseban parametar zahteva.

Redosled podupita je BM25, kNN, sparse — i MORA da prati redosled tezina u
search pipeline-u (`index_init/pipelines.py`). Zakljucano testom.

Retka grana ide kroz `neural_sparse` upit sa `query_tokens`: OpenSearch
(neural-search plugin, 2.11+) prima gotovu mapu token -> tezina, bez modela u
klasteru, i racuna skalarni proizvod sa `rank_features` poljem dokumenta — sto
je upravo leksicko poklapanje kako ga bge-m3 definise. Tokene racuna NAS
embedding servis, isti koji je racunao i tezine dokumenata, pa su kljucevi
(ID-jevi tokena) sa obe strane iz istog recnika.

Namerno NIJE zbir `rank_feature` upita sa `linear` funkcijom: `linear` je u
Elasticsearch dodat posle verzije od koje je OpenSearch odvojen. Oba oblika
treba potvrditi na domenu u integracionom prolazu — ovaj je izabran jer je
dokumentovan bas za ovu namenu.
"""

from typing import Any, Dict, List, Optional

DENSE_BM25 = "dense_bm25"
DENSE_BM25_SPARSE = "dense_bm25_sparse"
MODES = (DENSE_BM25, DENSE_BM25_SPARSE)

# Polja koja se NE vracaju iz pretrage: vektor od 1024 broja i retke tezine
# bi naduvali odgovor za desetine KB po pogotku, a nisu potrebni ni generatoru
# ni `query-log`-u.
_EXCLUDED_SOURCE = ["dense_vector", "sparse_weights"]

# Koliko najjacih tokena upita ulazi u retku granu. Pitanje od par recenica
# daje nekoliko desetina tokena; ogranicenje cuva upit malim i brzim, a tokeni
# ispod praga ionako jedva menjaju rezultat.
MAX_SPARSE_TERMS = 64


def bm25_subquery(question: str) -> Dict[str, Any]:
    return {"match": {"text": {"query": question}}}


def knn_subquery(vector: List[float], k: int) -> Dict[str, Any]:
    return {"knn": {"dense_vector": {"vector": list(vector), "k": k}}}


def sparse_subquery(weights: Dict[str, float]) -> Dict[str, Any]:
    """
    `neural_sparse` sa gotovim tokenima upita — skalarni proizvod retkih vektora.

    Tokeni su poredjani po tezini opadajuce i odseceni na MAX_SPARSE_TERMS.
    Redosled je deterministican (pri istoj tezini po tokenu), da isti upit
    uvek pravi isto telo — inace se dva evaluaciona prolaza ne bi mogla porediti.
    """
    terms = sorted(
        ((str(token), float(w)) for token, w in (weights or {}).items() if float(w) > 0),
        key=lambda item: (-item[1], item[0]),
    )[:MAX_SPARSE_TERMS]
    if not terms:
        # Upit bez ijednog tokena i dalje mora biti validan podupit; `match_none`
        # ne vraca nista i ne kvari normalizaciju ostalih grana.
        return {"match_none": {}}
    return {"neural_sparse": {"sparse_weights": {"query_tokens": dict(terms)}}}


def build_search_body(
    question: str,
    dense_vector: List[float],
    k: int,
    mode: str = DENSE_BM25,
    sparse_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Telo za `POST /<indeks>/_search?search_pipeline=<pipeline>`."""
    if mode not in MODES:
        raise ValueError("nepoznat oblik pretrage: {} (dozvoljeni: {})".format(
            mode, ", ".join(MODES)))
    if k <= 0:
        raise ValueError("k mora biti pozitivan")

    queries = [bm25_subquery(question), knn_subquery(dense_vector, k)]
    if mode == DENSE_BM25_SPARSE:
        queries.append(sparse_subquery(sparse_weights or {}))

    return {
        "size": k,
        "_source": {"excludes": list(_EXCLUDED_SOURCE)},
        "query": {"hybrid": {"queries": queries}},
    }


def parse_hits(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pogoci -> konteksti, u redosledu ranga.

    Vraca samo ono sto trebaju generator i `query-log`. `rank` pocinje od 1,
    jer je to broj koji se pojavljuje u promptu i u analizi rezultata.
    """
    contexts: List[Dict[str, Any]] = []
    for rank, hit in enumerate(response.get("hits", {}).get("hits", []), start=1):
        source = hit.get("_source", {})
        contexts.append(
            {
                "rank": rank,
                "score": hit.get("_score"),
                "chunk_id": source.get("chunk_id") or hit.get("_id"),
                "chunk_type": source.get("chunk_type"),
                "text": source.get("text", ""),
                "image_ref": source.get("image_ref"),
                "document_id": source.get("document_id"),
                "page": source.get("page"),
            }
        )
    return contexts
