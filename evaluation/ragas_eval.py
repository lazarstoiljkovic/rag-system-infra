"""
RAGAS ocenjivanje jednog evaluacionog prolaza, sa Claude-om kao sudijom.

    evaluation/.venv/bin/python evaluation/ragas_eval.py --run-id R

Radi nad lokalnim `manifest.jsonl` i `log.jsonl` (vidi `fetch_log.py`).
Rezultat: `scores.jsonl`, jedan red po (pitanje, varijanta).
Prekinuto ocenjivanje se nastavlja istom komandom.

Metrike (odeljak 2.5 rada):

  faithfulness       udeo tvrdnji iz odgovora potkrepljenih TEKSTOM konteksta
  mm_faithfulness    0/1: da li je odgovor veran tekstu I slikama koje je
                     generator video (u A nema slika, pa je to samo tekst)
  answer_accuracy    poklapanje sa ocekivanim odgovorom iz pitanja.json
                     (0, 0.25, ... 1; dva poziva sudiji sa zamenjenim redom)
  context_recall     koliko ocekivanog odgovora je pokriveno pronadjenim
                     kontekstom (o pretrazi, isto za A i B)

Zasto obe vernosti: obicna `Faithfulness` vidi samo tekst. U varijanti B
tvrdnja koju je generator tacno procitao SA SLIKE ispala bi "nepotkrepljena",
pa bi B bila kaznjena bas za ono sto rad meri. Razlika izmedju dve vernosti
pokazuje koliko odgovora pociva na slici, a ne na opisu.

Sudija je spoljni model (odluka 2026-10-01): sistem ostaje privatno hostovan,
a sudija je merni instrument van njega, nad sintetickim korpusom. Qwen nije
sudija jer bi ocenjivao sopstvene odgovore (pristrasnost prema sebi, odeljak
2.5.3 rada).

Claude se zove preko Anthropic-ovog sloja kompatibilnosti sa OpenAI API-jem,
jer RAGAS slike za sudiju salje u OpenAI formatu (`image_url`). Strukturisan
izlaz ide kroz instructor `Mode.MD_JSON` (vidi `build_metrics`).
"""

import argparse
import asyncio
import math
import os
import sys
import time
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lambda", "query_handler"))

from dataset import (append_jsonl, context_for_judge, join_records,  # noqa: E402
                     latest_by_key, load_questions, read_jsonl, run_dir)
from prompting import context_header  # noqa: E402

JUDGE_BASE_URL = "https://api.anthropic.com/v1/"
JUDGE_KEY_ENV = "ANTHROPIC_API_KEY"
JUDGE_MODEL = "claude-sonnet-5"
CONCURRENCY = 4

METRICS = ("faithfulness", "mm_faithfulness", "answer_accuracy", "context_recall")


CONFIG_PATH = os.path.join(HERE, "config.json")


def _api_key(env_name: str) -> str:
    """
    Kljuc iz okruzenja, ili iz `evaluation/config.json` (u .gitignore-u):
    {"ANTHROPIC_API_KEY": "..."}. Nikad iz koda.
    """
    if os.environ.get(env_name):
        return os.environ[env_name]
    if os.path.exists(CONFIG_PATH):
        import json
        with open(CONFIG_PATH, encoding="utf-8") as f:
            value = json.load(f).get(env_name)
        if value:
            return value
    raise SystemExit("nedostaje {} (okruzenje ili evaluation/config.json)".format(env_name))


def build_metrics(model: str):
    # Uvoz je ovde, a ne na vrhu: ostatak evaluation/ ne sme zavisiti od ragas-a.
    import instructor
    from openai import AsyncOpenAI
    from ragas.cache import DiskCacheBackend
    from ragas.llms.base import InstructorLLM, InstructorModelArgs
    from ragas.metrics.collections import (AnswerAccuracy, ContextRecall, Faithfulness,
                                           MultiModalFaithfulness)

    client = AsyncOpenAI(base_url=JUDGE_BASE_URL, api_key=_api_key(JUDGE_KEY_ENV), timeout=180)
    # Kes cuva odgovore sudije po promptu: ponovljeno ocenjivanje istih
    # odgovora ne kosta nista i daje iste ocene.
    cache = DiskCacheBackend(cache_dir=os.path.join(HERE, "results", ".ragas-cache"))
    # Ne `llm_factory`: on za OpenAI klijent bira instructor `Mode.JSON`, koji
    # salje `response_format={"type": "json_object"}`. Anthropic-ov sloj
    # kompatibilnosti to odbija (400, "Input should be 'json_schema'"), a i
    # `Mode.JSON_SCHEMA` (400, "json_schema.strict: Field required") — oba
    # utvrdjena probnim pozivom 2026-10-01. `Mode.MD_JSON` ne salje
    # `response_format` uopste: sema ide u prompt, a JSON se cita iz odgovora,
    # uz ponovni pokusaj ako ne prodje validaciju.
    llm = InstructorLLM(
        client=instructor.from_openai(client, mode=instructor.Mode.MD_JSON),
        model=model, provider="openai", cache=cache,
        model_args=InstructorModelArgs(max_tokens=2048),
    )
    # Ni `temperature` ni `top_p` se ne salju: Claude Sonnet 5 odbija
    # `temperature` sa 400 ("deprecated for this model", probni poziv
    # 2026-10-01). Ponovljivost ocena zato ne obezbedjuje temperatura, nego
    # kes iznad: ponovljeno ocenjivanje istih odgovora vraca iste ocene.
    llm.model_args.pop("temperature", None)
    llm.model_args.pop("top_p", None)
    return {
        "faithfulness": Faithfulness(llm=llm),
        "mm_faithfulness": MultiModalFaithfulness(llm=llm),
        "answer_accuracy": AnswerAccuracy(llm=llm),
        "context_recall": ContextRecall(llm=llm),
    }


def judge_inputs(record: Dict[str, Any], image_uri) -> Dict[str, Any]:
    """
    Ulazi za sudiju. Tekst konteksta je onakav kakav je video generator.

    Slike idu na KRAJ, posle svih tekstova, uz napomenu kom izvoru pripadaju.
    RAGAS svaki kontekst numerise sam ("Context 1, 2, ..."), pa bi slika
    ubacena izmedju tekstova pomerila tu numeraciju u odnosu na brojeve [n]
    kojima generator navodi izvore — i sudija bi tacan izvor proglasio
    pogresnim. Ovako "Context n" odgovara izvoru [n].
    """
    texts: List[str] = []
    images: List[str] = []
    ranks: List[str] = []
    attached = set(record["attachedImages"])
    for ctx in sorted(record["contexts"], key=lambda c: c.get("rank") or 0):
        texts.append(context_for_judge(ctx, context_header))
        if ctx.get("imageRef") in attached:
            images.append(image_uri(ctx["imageRef"]))
            ranks.append("[{}]".format(ctx.get("rank")))
    with_images = list(texts)
    if images:
        with_images.append("Slike koje slede su originalne slike izvora {}, tim redom.".format(
            ", ".join(ranks)))
        with_images.extend(images)
    return {"texts": texts, "with_images": with_images}


async def score_record(metrics, record, inputs, semaphore) -> Dict[str, Any]:
    row: Dict[str, Any] = {"id": record["id"], "variant": record["variant"],
                           "queryId": record["queryId"]}
    calls = {
        "faithfulness": lambda m: m.ascore(user_input=record["question"],
                                           response=record["answer"],
                                           retrieved_contexts=inputs["texts"]),
        "mm_faithfulness": lambda m: m.ascore(response=record["answer"],
                                              retrieved_contexts=inputs["with_images"]),
        "answer_accuracy": lambda m: m.ascore(user_input=record["question"],
                                              response=record["answer"],
                                              reference=record["reference"]),
        "context_recall": lambda m: m.ascore(user_input=record["question"],
                                             retrieved_contexts=inputs["texts"],
                                             reference=record["reference"]),
    }
    errors = {}
    async with semaphore:
        for name in METRICS:
            try:
                result = await calls[name](metrics[name])
                row[name] = float(result.value)
                if getattr(result, "reason", None):
                    row[name + "_reason"] = result.reason
            except Exception as error:  # noqa: BLE001 - jedna metrika ne rusi ceo prolaz
                row[name] = float("nan")
                errors[name] = "{}: {}".format(type(error).__name__, error)[:500]
    if errors:
        row["errors"] = errors
    return row


async def run(args):
    folder = run_dir(args.run_id)
    records = join_records(load_questions(), read_jsonl(os.path.join(folder, "manifest.jsonl")),
                           read_jsonl(os.path.join(folder, "log.jsonl")))
    records = [r for r in records if not r["error"]]
    if args.only:
        records = [r for r in records if r["id"] in set(args.only)]

    out_path = os.path.join(folder, "scores.jsonl")
    done = latest_by_key(read_jsonl(out_path), "id", "variant")
    todo = [r for r in records
            if (r["id"], r["variant"]) not in done or done[(r["id"], r["variant"])].get("errors")]
    if not todo:
        print("sve je vec ocenjeno: {}".format(os.path.relpath(out_path)))
        return

    model = args.model or JUDGE_MODEL
    metrics = build_metrics(model)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    bucket = None
    if any(r["attachedImages"] for r in todo):
        import aws_io
        bucket = aws_io.stack_outputs("RagStorageStack")["DataBucketName"]

    def image_uri(key):
        import aws_io
        return aws_io.image_data_uri(bucket, key, os.path.join(folder, "images"))

    started = time.monotonic()

    async def one(record):
        row = await score_record(metrics, record, judge_inputs(record, image_uri), semaphore)
        row["judgeModel"] = model
        append_jsonl(out_path, row)
        shown = " ".join("{}={:.2f}".format(m[:6], row[m]) for m in METRICS
                         if not math.isnan(row[m]))
        print("{:>4} {}  {}{}".format(record["id"], record["variant"], shown,
                                      "  GRESKE: " + ", ".join(row["errors"]) if row.get("errors") else ""),
              flush=True)

    await asyncio.gather(*(one(r) for r in todo))
    print("{} zapisa za {:.0f} s -> {}".format(len(todo), time.monotonic() - started,
                                              os.path.relpath(out_path)))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", help="drugi Claude model (podrazumevano {})".format(JUDGE_MODEL))
    parser.add_argument("--only", nargs="*", help="samo ova pitanja (npr. A4 H4)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
