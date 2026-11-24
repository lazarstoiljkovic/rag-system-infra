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

Dva EKSPERIMENTALNA pipeline-a (2026-11-23), samo za poredjenje oblika
pretrage; osnovna pretraga ih ne koristi:

  dense+bm25 RRF      isti upit, ali spajanje po RANGU (Reciprocal Rank
                      Fusion, `score-ranker-processor`, uveden u 2.19) umesto
                      min-max normalizacije ocena
  dense+bm25 lex      isti upit, tezine 2/3 BM25 : 1/3 kNN — isti udeo
                      leksickog signala kao u dense+bm25+sparse (BM25 i retka
                      grana su obe leksicke), ali bez retke grane. Razdvaja
                      "retka grana pomaze jer je pametna" od "pomaze jer
                      leksicki signal dobija vecu tezinu".
"""

from typing import Dict, List

DENSE_BM25 = "dense_bm25"
DENSE_BM25_SPARSE = "dense_bm25_sparse"
DENSE_BM25_RRF = "dense_bm25_rrf"
DENSE_BM25_LEX = "dense_bm25_lex"

# Ime pipeline-a po obliku pretrage. Imena citaju i QueryHandler (preko env
# promenljivih iz SearchStack-a), pa se ne menjaju bez izmene oba mesta.
PIPELINE_NAMES = {
    DENSE_BM25: "rag-hybrid-dense-bm25",
    DENSE_BM25_SPARSE: "rag-hybrid-dense-bm25-sparse",
    DENSE_BM25_RRF: "rag-hybrid-dense-bm25-rrf",
    DENSE_BM25_LEX: "rag-hybrid-dense-bm25-lex",
}

# Pipeline-i cije odbijanje NE obara deploy: sluze samo poredjenju. Osnovni
# pipeline-i su uslov rada sistema i njihovo odbijanje jeste greska.
EXPERIMENTAL = (DENSE_BM25_RRF, DENSE_BM25_LEX)

# Broj podupita po obliku pretrage, redom: BM25, kNN[, sparse].
SUBQUERY_COUNT = {DENSE_BM25: 2, DENSE_BM25_SPARSE: 3, DENSE_BM25_RRF: 2, DENSE_BM25_LEX: 2}

# Tezine (BM25, kNN) za lex: 2/3 + 1/3, kao leksicko : semanticko u obliku sa
# retkom granom.
LEX_WEIGHTS = [0.6667, 0.3333]

# RRF(deo) = suma po granama 1 / (RANK_CONSTANT + rang). 60 je vrednost iz
# originalnog rada (Cormack i dr., 2009) i podrazumevana u OpenSearch-u.
RRF_RANK_CONSTANT = 60


def equal_weights(count: int) -> List[float]:
    """Jednake tezine koje se sabiraju tacno u 1.0 (poslednja upija ostatak)."""
    if count <= 0:
        raise ValueError("broj podupita mora biti pozitivan")
    base = round(1.0 / count, 4)
    weights = [base] * (count - 1)
    weights.append(round(1.0 - sum(weights), 4))
    return weights


def weights_for(mode: str) -> List[float]:
    """Tezine po podupitima za pipeline-e sa min-max normalizacijom."""
    if mode == DENSE_BM25_LEX:
        return list(LEX_WEIGHTS)
    return equal_weights(SUBQUERY_COUNT[mode])


def pipeline_definition(mode: str) -> Dict:
    """Telo za `PUT /_search/pipeline/<ime>`."""
    if mode not in SUBQUERY_COUNT:
        raise ValueError("nepoznat oblik pretrage: {}".format(mode))
    if mode == DENSE_BM25_RRF:
        # RRF ne gleda ocene nego samo rang, pa nema ni normalizacije ni tezina.
        return {
            "description": "Hibridna pretraga ({}): RRF, rank_constant {}".format(
                mode, RRF_RANK_CONSTANT),
            "phase_results_processors": [
                {
                    "score-ranker-processor": {
                        "combination": {
                            "technique": "rrf",
                            "rank_constant": RRF_RANK_CONSTANT,
                        }
                    }
                }
            ],
        }
    weights = weights_for(mode)
    return {
        "description": "Hibridna pretraga ({}): min-max normalizacija, "
                       "tezine {}".format(mode, weights),
        "phase_results_processors": [
            {
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {"weights": weights},
                    },
                }
            }
        ],
    }
