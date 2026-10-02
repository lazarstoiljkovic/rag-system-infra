# Evaluacija

Merenje varijanti A i B nad skupom pitanja `corpus/demo/pitanja.json`:
metrike pretrage, RAGAS metrike (sudija Claude) i McNemar-ov test.

## Okruženje (jednom)

```bash
python3 -m venv evaluation/.venv
evaluation/.venv/bin/pip install -r evaluation/requirements.txt
export AWS_PROFILE=lazar-private
cp evaluation/config.example.json evaluation/config.json   # pa upisati ključ; fajl je u .gitignore-u
```

## Tok jednog prolaza

Koraci 1–2 traže podignut GPU i `RagSearchStack`; koraci 3–4 rade nad lokalnim
fajlovima u `evaluation/results/<run-id>/` i ne traže GPU.

```bash
RUN=eval-2026-10-05

# 1. sva pitanja, obe varijante, direktno preko Lambde (bez limita od 29 s)
evaluation/.venv/bin/python evaluation/run_queries.py --run-id $RUN
#    prekinut prolaz se nastavlja istom komandom; neuspela pitanja ponovo:
evaluation/.venv/bin/python evaluation/run_queries.py --run-id $RUN --retry-failed

# 2. zapisi iz query-log-a u lokalni log.jsonl
evaluation/.venv/bin/python evaluation/fetch_log.py --run-id $RUN

# 3. RAGAS, sudija Claude (spoljni API; korpus je sintetički). Ključ iz okruženja
#    ili iz evaluation/config.json: {"ANTHROPIC_API_KEY": "..."} — fajl je u .gitignore-u
evaluation/.venv/bin/python evaluation/ragas_eval.py --run-id $RUN

# 4. izveštaj -> results/$RUN/report.md; prvo pokretanje pravi prazan manual.csv
evaluation/.venv/bin/python evaluation/report.py --run-id $RUN
```

## Šta se meri

| Metrika | Izvor | Napomena |
|---|---|---|
| Hit@k, MRR, odziv dokumenata | `retrieval_metrics.py` | bez sudije; za „samo na slici“ relevantan je samo deo poreklom od slike |
| `faithfulness` | RAGAS | udeo tvrdnji potkrepljenih **tekstom** konteksta |
| `mm_faithfulness` | RAGAS | 0/1, sudija vidi i slike koje je generator video |
| `answer_accuracy` | RAGAS | poređenje sa očekivanim odgovorom; „tačno“ = ≥ 0,75 |
| `context_recall` | RAGAS | koliko očekivanog odgovora pokriva pronađeni kontekst |
| tačnost A/B | ručna ocena (`manual.csv`) | zlatni standard; McNemar-ov test, tačan oblik |

Sudija je samo Claude: Qwen bi ocenjivao sopstvene odgovore (pristrasnost prema
sebi, odeljak 2.5.3 rada). Sistem ostaje privatno hostovan; sudija je merni
instrument van njega, nad sintetičkim korpusom.

Obe vernosti se računaju za obe varijante: obična vidi samo tekst, pa bi tačnu
tvrdnju koju je B pročitao sa slike proglasila nepotkrepljenom. Razlika između
njih pokazuje koliko odgovora počiva na slici, a ne na opisu.

Kod koji ne zavisi od mreže (`dataset.py`, `retrieval_metrics.py`, `stats.py`)
testira se sa ostatkom: `python3 -m unittest discover -s test/python`.
