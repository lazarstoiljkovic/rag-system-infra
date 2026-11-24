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

Pojedinacne grane (dodato 2026-11-23): `bm25`, `dense` i `sparse` su TACNO
podupiti hibrida, pusteni sami, bez `hybrid` omotaca i bez search pipeline-a.
Sluze samo kao osnova za poredjenje: bez njih se ne moze pokazati da hibrid
na ovom korpusu pomaze, nego se to samo pretpostavlja. Osnovna pretraga
ostaje `dense_bm25` bez obzira na ishod tog poredjenja.

Varijante spajanja (isto 2026-11-23), sve sa ISTIM podupitima kao `dense_bm25`:

  dense_bm25_rrf    spajanje po rangu (RRF) umesto min-max normalizacije
  dense_bm25_lex    tezine 2/3 BM25 : 1/3 kNN umesto 1/2 : 1/2
  dense_bm25_deep   50 kandidata po grani umesto k (`pagination_depth`):
                    min-max se tada racuna nad 50, a ne nad 5 kandidata.
                    Bez `pagination_depth` svaka grana vraca `size` pogodaka,
                    a deo koga nema u jednoj grani dobija za nju 0 uz punu
                    tezinu (neural-search 2.19, ScoreCombiner) — pa deo koji
                    nadje samo jedna grana dobija najvise 0.5.
"""

from typing import Any, Dict, List, Optional

DENSE_BM25 = "dense_bm25"
DENSE_BM25_SPARSE = "dense_bm25_sparse"
DENSE_BM25_RRF = "dense_bm25_rrf"
DENSE_BM25_LEX = "dense_bm25_lex"
DENSE_BM25_DEEP = "dense_bm25_deep"
BM25 = "bm25"
DENSE = "dense"
SPARSE = "sparse"

# Hibridni oblici idu kroz search pipeline (normalizacija + kombinacija ocena);
# pojedinacne grane ne, jer nemaju sta da spajaju.
HYBRID_MODES = (DENSE_BM25, DENSE_BM25_SPARSE, DENSE_BM25_RRF, DENSE_BM25_LEX, DENSE_BM25_DEEP)
SINGLE_MODES = (BM25, DENSE, SPARSE)
MODES = HYBRID_MODES + SINGLE_MODES

# Broj kandidata po grani za `dense_bm25_deep`. Korpus ima 109 delova, pa je
# 50 vec skoro pola korpusa; dokumentacija normalizacije preporucuje 100-200
# za velike skupove.
DEEP_CANDIDATES = 50

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
    """
    Telo za `POST /<indeks>/_search`; hibridni oblici jos traze
    `?search_pipeline=<pipeline>` (vidi `uses_pipeline`).
    """
    if mode not in MODES:
        raise ValueError("nepoznat oblik pretrage: {} (dozvoljeni: {})".format(
            mode, ", ".join(MODES)))
    if k <= 0:
        raise ValueError("k mora biti pozitivan")

    if mode == BM25:
        query = bm25_subquery(question)
    elif mode == DENSE:
        query = knn_subquery(dense_vector, k)
    elif mode == SPARSE:
        query = sparse_subquery(sparse_weights or {})
    else:
        deep = mode == DENSE_BM25_DEEP
        queries = [bm25_subquery(question),
                   knn_subquery(dense_vector, DEEP_CANDIDATES if deep else k)]
        if mode == DENSE_BM25_SPARSE:
            queries.append(sparse_subquery(sparse_weights or {}))
        query = {"hybrid": {"queries": queries}}
        if deep:
            query["hybrid"]["pagination_depth"] = DEEP_CANDIDATES

    return {
        "size": k,
        "_source": {"excludes": list(_EXCLUDED_SOURCE)},
        "query": query,
    }


def pipeline_key(mode: str) -> Optional[str]:
    """
    Kroz koji search pipeline ide oblik pretrage (kljuc u `PIPELINE_NAMES`),
    ili None za pojedinacnu granu. `deep` menja samo broj kandidata, a spaja
    isto kao osnova.
    """
    if mode not in HYBRID_MODES:
        return None
    return DENSE_BM25 if mode == DENSE_BM25_DEEP else mode


def uses_pipeline(mode: str) -> bool:
    """Da li oblik pretrage trazi search pipeline (samo hibridni)."""
    return pipeline_key(mode) is not None


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
