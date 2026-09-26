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

Dokumenti su povezani (isti servisi, isti timovi, isti incident), pa postoje
i pitanja čiji odgovor traži dva dokumenta.

## Generisanje

```bash
python3 -m venv /tmp/corpus-venv
/tmp/corpus-venv/bin/pip install PyMuPDF==1.24.14 python-docx==1.1.2 matplotlib
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

`pitanja.json`: 47 pitanja — 20 „samo na slici“ (od toga 4 namerno teška za
opis rečima: pripadnost namespace-u ili kancelariji, strelica bez natpisa),
4 kroz dva dokumenta. Na teškim pitanjima (F3, K3, K4, O3) očekuje se razlika između
varijante A (samo opis slike) i B (opis + slika) — dobri kandidati za prikaz
ablacije na prezentaciji. Korpus još nije pušten kroz sistem; koja pitanja
najbolje pokazuju razliku, zna se tek posle prvog prolaza.
