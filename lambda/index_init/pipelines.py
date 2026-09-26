"""
Search pipeline-i za hibridnu pretragu. Ciste funkcije, bez mreze.

Hibridni upit u OpenSearch-u vraca rezultate vise podupita (BM25, kNN, ...)
cije ocene NISU uporedive: BM25 je neogranicen, kosinusna slicnost je u [0, 1].
Normalization processor ih prvo svodi na isti opseg (min-max), pa kombinuje
tezinskom aritmetickom sredinom. Bez pipeline-a hibridni upit ili pada ili
sabira neuporedive brojeve.

Dva pipeline-a, jer broj tezina mora tacno odgovarati broju podupita:

  dense+bm25          osnovna pretraga, kako je specificirano u radu
  dense+bm25+sparse   sekundarni eksperiment (odluka 2026-09-26): isti upit
                      uz treci podupit nad `sparse_weights`

Tezine su jednake — namerno neutralan izbor. Podesavanje tezina bi samo po
sebi bio eksperiment, a rad meri nesto drugo; jednake tezine su najlakse za
obrazloziti i ne favorizuju nijednu granu.

REDOSLED TEZINA mora da prati redosled podupita u upitu: BM25, kNN, sparse.
Taj redosled odredjuje `query_handler/retrieval.py`, i isti je zakljucan
testom sa obe strane.
"""

from typing import Dict, List

DENSE_BM25 = "dense_bm25"
DENSE_BM25_SPARSE = "dense_bm25_sparse"

# Ime pipeline-a po obliku pretrage. Imena citaju i QueryHandler (preko env
# promenljivih iz SearchStack-a), pa se ne menjaju bez izmene oba mesta.
PIPELINE_NAMES = {
    DENSE_BM25: "rag-hybrid-dense-bm25",
    DENSE_BM25_SPARSE: "rag-hybrid-dense-bm25-sparse",
}

# Broj podupita po obliku pretrage, redom: BM25, kNN[, sparse].
SUBQUERY_COUNT = {DENSE_BM25: 2, DENSE_BM25_SPARSE: 3}


def equal_weights(count: int) -> List[float]:
    """Jednake tezine koje se sabiraju tacno u 1.0 (poslednja upija ostatak)."""
    if count <= 0:
        raise ValueError("broj podupita mora biti pozitivan")
    base = round(1.0 / count, 4)
    weights = [base] * (count - 1)
    weights.append(round(1.0 - sum(weights), 4))
    return weights


def pipeline_definition(mode: str) -> Dict:
    """Telo za `PUT /_search/pipeline/<ime>`."""
    if mode not in SUBQUERY_COUNT:
        raise ValueError("nepoznat oblik pretrage: {}".format(mode))
    return {
        "description": "Hibridna pretraga ({}): min-max normalizacija, "
                       "jednake tezine".format(mode),
        "phase_results_processors": [
            {
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {"weights": equal_weights(SUBQUERY_COUNT[mode])},
                    },
                }
            }
        ],
    }


def all_pipelines() -> Dict[str, Dict]:
    """Ime pipeline-a -> telo, za sve oblike pretrage."""
    return {PIPELINE_NAMES[mode]: pipeline_definition(mode) for mode in PIPELINE_NAMES}
