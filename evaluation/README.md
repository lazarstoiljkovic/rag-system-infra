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

## Poređenje oblika pretrage (samo pretraga)

Da li hibrid na ovom korpusu zaista pomaže? Bez pojedinačnih grana to se samo
pretpostavlja. Merenje ide bez generisanja i bez sudije, nad istim indeksom kao
glavno merenje. Osnovna pretraga ostaje `dense_bm25` bez obzira na ishod.

```bash
D=2026-11-24
# 0. sveže podignut RagSearchStack + GPU (bge-m3 za vektor pitanja); indeks iz
#    embedded.json u S3 — isti opisi i vektori kao u eval-2026-10-02, bez VLM-a
evaluation/.venv/bin/python evaluation/reindex_from_s3.py --dry-run
evaluation/.venv/bin/python evaluation/reindex_from_s3.py

# 1. osam oblika, samo pretraga (varijanta A)
MODES="dense_bm25 dense_bm25_sparse dense_bm25_rrf dense_bm25_lex dense_bm25_deep bm25 dense sparse"
for M in $MODES; do
  evaluation/.venv/bin/python evaluation/run_queries.py --run-id ret-$D-$M --retrieval $M --retrieval-only
  evaluation/.venv/bin/python evaluation/fetch_log.py --run-id ret-$D-$M
done

# 2. jedna tabela, po tipu pitanja, McNemar prema osnovi (sirovo p i Holm)
#    (eval-2026-10-02 uz to proverava ponovljivost: dense_bm25 mora dati isto)
evaluation/.venv/bin/python evaluation/compare_retrieval.py --baseline ret-$D-dense_bm25 \
  --runs $(for M in $MODES; do printf "ret-$D-$M "; done) eval-2026-10-02
```

| Oblik | Šta se menja u odnosu na osnovu | Pitanje |
|---|---|---|
| `bm25`, `dense`, `sparse` | samo jedna grana (tačno podupit hibrida, bez pipeline-a) | da li hibrid uopšte pomaže |
| `dense_bm25_sparse` | treća, retka grana | već izmereno 2. 10. |
| `dense_bm25_rrf` | spajanje po rangu (RRF, k = 60) umesto min-max | da li je min-max dobar izbor |
| `dense_bm25_lex` | težine 2/3 BM25 : 1/3 kNN | da li retka grana pomaže sama, ili samo zato što leksički signal dobija 2/3 težine |
| `dense_bm25_deep` | 50 kandidata po grani (`pagination_depth`) umesto 5 | da li normalizacija nad samo 5 kandidata spušta slike |

Pipeline-i za RRF i lex su eksperimentalni: ako ih domen odbije, `IndexInit`
to upiše u log i deploy ide dalje, a merenje tog oblika pada sa greškom u
`query-log`-u.

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
