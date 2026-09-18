# Kontekst projekta — privatno hostovani RAG sistem (diplomski rad)

**Naslov (usaglasen sa mentorom):** Projektovanje i implementacija privatno
hostovanog RAG sistema za pitanja i odgovore nad tehnickom dokumentacijom

**Fakultet:** Elektronski fakultet Nis, Katedra za racunarstvo

---

## Terminoloska ogranicenja (trazi mentor, ne menjati bez razloga)

- **"self-hosted" -> "privatno hostovan"** kroz ceo rad i kod (komentari, imena
  resursa gde ima smisla).
- **"multimodalni" se NE koristi u nazivu sistema/rada.** Sistem pretrazuje
  iskljucivo tekstualni vektorski prostor (tekst + tekstualni opisi slika,
  embedovani istim tekstualnim modelom). Ovo NIJE zajednicka multimodalna
  vektorizacija teksta i slike (kakvu rade CLIP-tip modeli). Ne implementirati
  nista sto bi to precutno promenilo — npr. ne uvoditi CLIP embedding bez
  eksplicitnog dogovora.
- **Korpus je sinteticki** (dokumentacija fiktivne kompanije) — namerno, radi
  izbegavanja kontaminacije pretreninga generativnog modela. Model ne sme moci
  da "pogodi" odgovor bez retrievala, inace merenje faithfulness metrike gubi
  smisao.

## Pet podsistema

1. **External Knowledge Base** — tekst, tabele (born-digital), slike/dijagrami.
2. **Data Preparation & Ingestion**
   - ekstrakcija sa grananjem: tekst / tabela / slika
   - chunking teksta: fiksno 512 znakova, 50 overlap
   - serijalizacija tabela u Markdown — **deterministicki, bez VLM poziva**
   - captioning slika: VLM, **dva razlicita prompta** (dijagram arhitekture:
     komponente, tip veze, pravac strelica / grafikon: tip, ose, tacne vrednosti).
     Uz caption se cuva `image_ref` na original.
   - embedding: bge-m3, **svi tipovi chunkova kroz isti tekstualni model**
3. **Vector Database — OpenSearch.** Hibridna sema: `text` (BM25) +
   `dense_vector` (kNN/HNSW) + `sparse_weights` + metapodaci + `image_ref`
   (kljucno polje — omogucava generatoru da dobije originalnu sliku, ne samo caption).
4. **Retriever** — query embed (bge-m3) -> hibridna pretraga (dense + BM25) ->
   top-k. **Bez re-rankera**, opravdano GPU budzetom (24GB VRAM).
5. **Generator — VLM (Qwen2.5-VL-7B-Instruct).** ISTI model radi i captioning i
   generisanje. Namerna odluka: (a) eksperimentalna cistoca — ablacija A/B mora
   izolovati samo "da li generator vidi sliku", ne i razliku u modelu;
   (b) jedan model manje na 24GB kartici.

### Ablacija — glavni empirijski doprinos

- **Varijanta A** (Opcija 2, MRAG taksonomija): generator vidi SAMO tekst
  (caption umesto slike), nikad sirovu sliku.
- **Varijanta B** (Opcija 3): kad je retrieved chunk poreklom od slike,
  generatoru se prosledjuje i caption I originalna slika (preko `image_ref`).

## Serving sloj

- vLLM, OpenAI-compatible API.
- Port **8000** — Qwen2.5-VL (captioning + generisanje).
- Port **8001** — bge-m3 embedding (moze na CPU ako VRAM postane usko grlo).
- GPU: `g5.xlarge` (1x NVIDIA A10G, 24GB VRAM).

**Ispravka na raniju dokumentaciju:** "AWQ 8-bit" ne postoji — AWQ je metoda
4-bitne kvantizacije tezina. A10G je Ampere (sm_86) i nema FP8 podrsku (trazi
Ada/Hopper). Realne opcije na 24GB: FP16 (~16GB, tesno sa KV cache-om) ili
AWQ 4-bit (~5-6GB, komotno).

## AWS arhitektura — LEAN verzija

Cetiri sloja. Kljucni princip: **Lambda nema GPU podrsku**, pa je svaka funkcija
koja dotice model tanak HTTP klijent ka EC2 instanci. To je razlog cele podele.

| Sloj | Servisi |
|---|---|
| Control plane (ingestion) | Step Functions + 5 Lambdi (Python) |
| Inference plane | EC2 g5.xlarge + vLLM |
| Storage plane | S3 (1 bucket, 3 prefiksa), OpenSearch domen, DynamoDB (2 tabele) |
| Query plane | API Gateway + JEDNA Lambda (QueryHandler) |

### Odstupanje od dokumentacije: sedmi stack (`search-stack`)

Dokumentacija nabraja sest stack-ova i ne smesta OpenSearch ni u jedan.
Odluka: **OpenSearch dobija svoj `search-stack`**, ne ide u `storage-stack`.

Razlog nije trosak nego priroda podataka. Indeks je **izveden podatak** — svaki
chunk, vektor i caption moze se ponovo napraviti pokretanjem ingestiona nad
`raw/` prefiksom. S3 i DynamoDB drze ono sto se ne moze regenerisati:
originalne dokumente i `query-log` na kome stoji cela RAGAS evaluacija. Da su u
istom stack-u, jedna `cdk destroy` komanda brisala bi i jedno i drugo.

Uz to je OpenSearch druga najskuplja stavka posle GPU-a (~0.036 USD/h, non-stop),
pa se tokom pauza isplati srusiti ga — sto se sme samo ako S3 ostaje netaknut.

Granularnost stack-ova time prati **zivotni ciklus podataka**, ne taksonomiju
AWS servisa. To je isti argument kojim je vec opravdano izdvajanje GPU sloja i
vredi ga navesti u poglavlju 3.2 rada.

### Eksplicitno ODBACENO za implementaciju (ide u "buduci rad", ne u kod)

- **Interni ALB** — za jednu GPU instancu nema koristi. Lambda cita IP instance
  preko `ec2:DescribeInstances`, filtrirano po tagu `Name=vllm-server`.
- **Pun custom VPC sa NAT Gateway-om** — EC2 ide u public subnet sa
  restriktivnom SG (SG-to-SG, ne 0.0.0.0/0).
- **EventBridge auto-stop** — GPU se pali/gasi RUCNO preko CLI-ja.
- **CloudFront** — cist S3 static website hosting.
- **Tri odvojena S3 bucket-a** — jedan sa prefiksima je dovoljno.

## Tokovi

**Ingestion** (S3 `raw/` -> EventBridge -> Step Functions):

1. `ExtractAndPrepare` — ekstrakcija (PyMuPDF/python-docx), chunking,
   serijalizacija tabela; manifest "pending chunks" u S3
2. Map state, paralelno po chunk-u: `tip=="image"` -> `CaptionChunk` (HTTP ka VLM),
   `tip=="text"|"table"` -> prosledi bez izmene
3. `EmbedChunks` — **BATCH** poziv, ne po chunk-u
4. `IndexChunks` — bulk indeksiranje u OpenSearch
5. `FinalizeIngestion` — status u `ingestion-log`

Pet Lambdi, ne 10-15: granularnost prati prirodnu podelu posla (CPU-bound
ekstrakcija / GPU-pozivajuci koraci / I/O-bound indeksiranje).

**Query** (API Gateway POST /query -> jedna Lambda, sinhrono):
embedding -> hibridna pretraga -> prompt (Varijanta A ili B) -> VLM ->
upis u `query-log` -> odgovor.

`query-log` je **direktan izvor podataka za RAGAS evaluaciju**, ne debug log.

> **Pazi:** API Gateway integration timeout je **29s, tvrd limit**.

## Okruzenje

- CDK u TypeScript-u, Lambda kod u Python-u (`@aws-cdk/aws-lambda-python-alpha`,
  `PythonFunction` — **zahteva lokalno pokrenut Docker**).
- Region: **eu-central-1** (Frankfurt).
- AWS profil: **`lazar-private`** — NIJE default profil. Na ovoj masini postoji i
  drugi, default nalog; paziti da se ne deploy-uje na pogresan.
- Node: 22 (vidi `.nvmrc`). Globalni `nvm` default je stariji i namerno se ne dira.

```bash
export AWS_PROFILE=lazar-private
nvm use            # cita .nvmrc
aws sts get-caller-identity   # proveriti da je vracen nalog onaj privatni
```

## Repo

`github.com/lazarstoiljkovic/rag-system-infra` (public).

Zato u repou nema broja AWS naloga: `cdk.context.json` je u `.gitignore` jer mu
je broj naloga deo kljuca lookup-a. Prava IP adresa se prosledjuje preko
`-c developerCidr=...`, nikad se ne upisuje u `cdk.json`.

## Stanje

Bootstrap za `eu-central-1` je uradjen.

| Faza | Stack | Stanje |
|---|---|---|
| 0 | skelet, `bin/app.ts`, bootstrap | gotovo |
| 1 | `network-stack`, `storage-stack` | napisano, nije deploy-ovano |
| 2 | `model-serving-stack` | **blokirano kvotom** |
| 3 | `search-stack` — OpenSearch domen + hibridna sema | nije poceto |
| 4 | `ingestion-stack` | nije poceto |
| 5 | `query-stack` | nije poceto |
| 6 | korpus, RAGAS, UI | nije poceto |

### Blokator: GPU kvota

Nalog nema kvotu ni za jednu GPU instancu (EC2 G/VT on-demand i spot = 0,
EC2 P = 0, SageMaker ml.g5.* = 0). Zahtev je podnet 2026-09-18:

```bash
aws service-quotas list-requested-service-quota-change-history-by-quota \
  --service-code ec2 --quota-code L-DB2E81BA \
  --region eu-central-1 --profile lazar-private \
  --query "RequestedQuotas[].[Status,DesiredValue,Created]" --output text
```

Dok kvota ne stigne, faze 1, 3 i 4 nisu blokirane: bge-m3 moze na CPU
(`t3.large` staje u postojecu kvotu od 5 vCPU za standardne instance), pa ceo
ingestion i retrieval put moze da se testira stvarno — samo captioning i
generisanje ostaju stub.

## Sledeci korak

1. `cdk deploy RagNetworkStack` + `RagStorageStack` — traje minut, kosta nista,
   a potvrdjuje da profil stvarno ima permisije za deploy. Bolje da pukne na
   VPC-u nego kasnije usred Step Functions stack-a.
2. Faza 3 — `search-stack`. Ne zavisi od GPU-a i blokira fazu 4, dakle
   najkorisnija stvar dok kvota ceka.

## Poznati rizici

- Deep Learning AMI: stvarno ime je `Deep Learning OSS Nvidia Driver AMI GPU
  PyTorch * (Ubuntu 24.04)`. Pattern `Deep Learning AMI GPU PyTorch*` iz ranije
  dokumentacije **nece naci nista**.
- vLLM cold start (ucitavanje 7B modela u VRAM) traje desetine sekundi do par
  minuta — ne testirati cim EC2 predje u "running", cekati `/health`.
- bge-m3 nema potvrdenu validaciju za srpski u zvanicnim benchmarcima
  (MIRACL/MKQA). Deklarisana je podrska za "100+ jezika", ali ne tvrditi
  "dokazano najbolji za srpski" bez sopstvene empirijske provere.
- `cdk destroy --all` brise i S3 bucket sa podacima. Pre finalne evaluacije
  postaviti `retainData: true` u `bin/app.ts`.
