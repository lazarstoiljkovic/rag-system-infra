# Demo korpus: Nexa Tech Solutions d.o.o.

Interna tehnička dokumentacija **izmišljene** softverske firme koja razvija
web aplikacije. Glavni proizvod je **Nexa Booking**, SaaS aplikacija za online
zakazivanje termina. Sve je sintetičko (firma, proizvod, brojevi, incidenti),
namerno: model ne sme moći da pogodi odgovor bez pretrage dokumenata.

## Dokumenti

| Dokument | Format | Sadržaj |
|---|---|---|
| `booking-arhitektura` | PDF | servisi (tabela), komponente sistema (dijagram), p95 latencija po endpoint-u (grafikon) |
| `ci-cd-proces` | PDF | okruženja (tabela), faze pipeline-a (dijagram), trajanje pipeline-a (grafikon) |
| `frontend-standardi` | DOCX | pravila i provere (tabela), tok podataka u frontendu (dijagram) |
| `booking-api-v3` | PDF | endpoint-i (tabela), tok nove rezervacije (dijagram) |
| `sla-i-podrska` | PDF | planovi podrške (tabela), put tiketa (dijagram), uptime po mesecima (grafikon) |
| `izvestaj-performanse-q2-2026` | DOCX | load test (tabela), incident u maju, LCP po stranici (grafikon) |
| `plan-migracije-kubernetes` | PDF | faze migracije (tabela), ciljna arhitektura po namespace-ovima (dijagram), troškovi (grafikon) |

Opšti dokumenti firme — čine korpus realnijim i služe kao „ometači“ pretrage:

| Dokument | Format | Sadržaj |
|---|---|---|
| `pravilnik-o-radu` | DOCX | radno vreme, hibridni rad, godišnji odmor, plaćena odsustva (tabela), odobravanje odsustva (dijagram) |
| `organizacija-i-pozicije` | PDF | zaposleni i kancelarije, pozicije i rasponi zarada (tabela), organizaciona šema po kancelarijama (dijagram) |
| `finansijski-izvestaj-h1-2026` | PDF | prihod i rast, prihod po izvoru (tabela), prihod po mesecima i struktura troškova (grafikoni) |
| `politika-bezbednosti` | PDF | lozinke i 2FA, klasifikacija podataka (tabela), prijava incidenta (dijagram) |

Proširenje (oktobar 2026, `documents_dodatni.py`) — nove vrste slika, ometači i
još opštih dokumenata:

| Dokument | Format | Sadržaj |
|---|---|---|
| `tok-placanja` | PDF | statusi plaćanja (tabela), sekvenca poruka pri plaćanju (dijagram sekvence) |
| `mrezna-topologija` | PDF | pravila pristupa (tabela), komponente po zonama i podmrežama (dijagram) |
| `monitoring-i-alarmi` | DOCX | alarmi (tabela), error rate po servisu (linijski, više serija, bez ispisanih vrednosti), broj alarma |
| `kapacitet-baze-2026` | PDF | serveri baze (tabela), opterećenje CPU-a (grupisani stubići), zauzeće po tabelama (torta) |
| `roadmap-2027` | PDF | projekti i timovi (tabela), vremenski plan (Gantt, bez datuma) |
| `booking-arhitektura-2-2` | PDF | **ometač**: zastarela arhitektura 2.2 — drugi portovi, sinhrone notifikacije, latencija iz 2025. |
| `sla-i-podrska-2025` | PDF | **ometač**: SLA koji je prestao da važi — drugi uptime i cene, uptime Q4 2025. |
| `procedura-onboardinga` | DOCX | prva nedelja (tabela), priprema pre dolaska (dijagram) |
| `ugovor-o-obradi-podataka` | PDF | podobrađivači i zemlje obrade (tabela), bez slika |
| `pravilnik-o-putovanjima` | DOCX | dnevnice (tabela), odobravanje po iznosu (dijagram) |
| `kodeks-ponasanja` | PDF | samo tekst |

Ometači postoje zato što je pretraga nad prvih 11 dokumenata bila prelaka
(Hit@5 = 0,98): pretraga sada mora da nađe važeću verziju dokumenta.

Dokumenti su povezani (isti servisi, isti timovi, isti incident), pa postoje
i pitanja čiji odgovor traži dva dokumenta.

## Generisanje

```bash
python3 -m venv /tmp/corpus-venv
/tmp/corpus-venv/bin/pip install PyMuPDF python-docx matplotlib
/tmp/corpus-venv/bin/python corpus/demo/generate.py
```

Pravi `dokumenti/` i `pitanja.json`, pa proverava:
- da odgovor na svako pitanje „samo na slici“ ne postoji ni u jednom tekstu
  korpusa, a postoji na slici;
- da ostali odgovori postoje u tekstu;
- koliko chunkova daje pravi ekstraktor iz Lambde.

Za indeksiranje: sadržaj `dokumenti/` u `raw/` prefiks bucket-a. Test
dokument (`corpus/test/`) NE ubacivati uz ovaj korpus.

## Pitanja

`pitanja.json`: 106 pitanja — 56 „samo na slici“ (od toga 15 namerno teških za
opis rečima: pripadnost zoni, podmreži, namespace-u ili kancelariji; vrednosti
sa linijskog grafikona bez ispisanih brojeva; preklapanje i trajanje na Gantt
planu), 7 kroz dva dokumenta. Pitanja iz proširenja su u `questions_dodatna.py`.

Broj pitanja „samo na slici“ je povećan sa 20 posle prvog merenja: sa 5
neslaganja između varijanti A i B tačan McNemar-ov test ne može ispod
p = 0,0625, pa razlika ne bi mogla biti dokazana ni kad postoji.

Oznaka `naziv_i_u_tekstu` označava pitanje čiji je odgovor naziv (servisa,
projekta) koji postoji i u tekstu, dok sama činjenica (koji od njih) postoji
samo na slici; za takva pitanja provera curenja se preskače, uz obavezno
obrazloženje u `napomena`.

Četiri postojeća pitanja (A1, A4, S1, S2) imaju precizniji tekst
(`izmene_postojecih`), jer bi ih ometači inače učinili dvosmislenim.
