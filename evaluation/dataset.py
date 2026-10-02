"""
Skup pitanja, grupe pitanja i spajanje zapisa jednog evaluacionog prolaza.
Ciste funkcije, bez mreze i bez ragas-a, da bi se testirale lokalno.

Tri izvora se spajaju u jedan zapis po paru (pitanje, varijanta):

  pitanja.json   ocekivani odgovor, dokumenti u kojima je odgovor, grupe
  manifest       koje je pitanje dobilo koji `queryId` (pise `run_queries.py`)
  log            zapis iz `query-log`-a: konteksti, odgovor, poslate slike

`query-log` namerno ne cuva oznaku pitanja (A4, H4...) jer ne zna za skup
pitanja; zato manifest. Spajanje ide po `queryId`, ne po tekstu pitanja.

Sintaksa ogranicena na Python 3.9, kao i ostatak testova.
"""

import json
import os
from typing import Any, Dict, Iterable, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_PATH = os.path.join(HERE, "..", "corpus", "demo", "pitanja.json")
RESULTS_DIR = os.path.join(HERE, "results")

VARIANTS = ("A", "B")

# Grupe po kojima se izvestaj deli. Jedno pitanje pripada vise grupa.
ALL = "sva"
IMAGE_ONLY = "samo_na_slici"
HARD = "tesko_za_opis"
TEXT = "tekst_tabela_vise"
GROUPS = (ALL, IMAGE_ONLY, HARD, TEXT)


def load_questions(path: str = QUESTIONS_PATH) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        questions = json.load(f)
    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("oznake pitanja nisu jedinstvene")
    return questions


def groups_of(question: Dict[str, Any]) -> List[str]:
    """Grupe kojima pitanje pripada; `sva` uvek prva."""
    groups = [ALL]
    if question.get("samo_na_slici"):
        groups.append(IMAGE_ONLY)
        if question.get("tesko_za_opis"):
            groups.append(HARD)
    else:
        groups.append(TEXT)
    return groups


def run_dir(run_id: str) -> str:
    return os.path.join(RESULTS_DIR, run_id)


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path: str, row: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def latest_by_key(rows: Iterable[Dict[str, Any]], *keys: str) -> Dict[tuple, Dict[str, Any]]:
    """
    Poslednji zapis po kljucu. Manifest i ocene se samo dopisuju (ponovni
    pokusaj neuspelog pitanja dodaje novi red), pa vazi poslednji.
    """
    out: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        out[tuple(row[k] for k in keys)] = row
    return out


def context_for_judge(ctx: Dict[str, Any], header) -> str:
    """
    Kontekst onako kako ga je video generator: zaglavlje pa tekst.
    `header` je `prompting.context_header`, da sudija i generator vide isti
    oblik, a da se pravilo ne duplira.
    """
    as_prompt = {
        "rank": ctx.get("rank"),
        "chunk_type": ctx.get("chunkType"),
        "document_id": ctx.get("documentId"),
        "page": ctx.get("page"),
    }
    return "{}\n{}".format(header(as_prompt), (ctx.get("text") or "").strip())


def join_records(
    questions: List[Dict[str, Any]],
    manifest: List[Dict[str, Any]],
    log_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Jedan zapis po (pitanje, varijanta) za koje postoji uspesan odgovor.
    Neuspesna pitanja se ne gube tiho: vracaju se sa `error`, a izvestaj ih
    broji posebno.
    """
    by_id = {q["id"]: q for q in questions}
    log_by_query = {item["queryId"]: item for item in log_items}
    records = []
    for (qid, variant), entry in sorted(latest_by_key(manifest, "id", "variant").items()):
        question = by_id.get(qid)
        if question is None:
            raise ValueError("manifest pominje nepoznato pitanje: {}".format(qid))
        item: Optional[Dict[str, Any]] = log_by_query.get(entry.get("queryId"))
        error = entry.get("error") or (item or {}).get("error")
        if item is None and not error:
            error = "zapis nije pronadjen u query-log-u"
        records.append({
            "id": qid,
            "variant": variant,
            "queryId": entry.get("queryId"),
            "question": question["pitanje"],
            "reference": question["odgovor"],
            "documents": list(question["dokumenti"]),
            "imageOnly": bool(question.get("samo_na_slici")),
            "groups": groups_of(question),
            "contexts": (item or {}).get("contexts", []),
            "attachedImages": (item or {}).get("attachedImages", []),
            "answer": (item or {}).get("answer", ""),
            "error": error,
        })
    return records
