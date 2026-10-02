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

- Port **8000** — vLLM, OpenAI-compatible API, Qwen2.5-VL-7B-Instruct-AWQ
  (captioning + generisanje).
- Port **8001** — bge-m3 embedding. **Nije vLLM**, nego tanak FastAPI omotac
  oko FlagEmbedding referentne implementacije. Razlog je u sledecem pasusu.
- GPU: `g5.xlarge` (1x NVIDIA A10G, 24GB VRAM). Oba servisa dele istu karticu.

**Zasto embedding nije na vLLM-u.** vLLM embedding endpoint vraca samo guste
vektore, a sema indeksa ima i `sparse_weights`. Leksicke tezine bge-m3 daje
jedino referentna FlagEmbedding implementacija (`BGEM3FlagModel` sa
`return_sparse=True`). Servis izlaze oba oblika: `/v1/embeddings` je
OpenAI-kompatibilan i vraca guste vektore, a `/embed` vraca i guste i retke.

> **Odluka o `sparse_weights` (2026-09-26).** Ostaje u semi i ULAZI u pretragu,
> ali kao **sekundarni eksperiment**, ne kao podrazumevano. Osnovna pretraga
> ostaje "dense + BM25", kako je specificirano; poredi se sa
> "dense + BM25 + sparse" kao trecim podupitom hibridnog upita. Obrazlozenje
> za rad: podaci su vec u indeksu (eksperiment je skoro besplatan), a bez
> ovoga bi `sparse_weights` bio mrtav podatak i pao bi jedini razlog sto
> embedding servis nije na vLLM-u. Ovaj eksperiment je o RETRIEVAL-u i
> odvojen je od glavne ablacije A/B (koja je o generatoru).

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
| 1 | `network-stack`, `storage-stack` | **deploy-ovano, stoji na nalogu** |
| 2 | `model-serving-stack` | **deploy-ovano i funkcionalno provereno** |
| 3 | `search-stack` — OpenSearch domen + hibridna sema | **provereno pa sruseno radi ustede** |
| 4 | `ingestion-stack` | **deploy-ovano i provereno end-to-end (2026-09-26)** |
| 5 | `query-stack` | **deploy-ovano i provereno end-to-end (2026-09-26)** |
| 6 | korpus, RAGAS, UI | **demo korpus Nexa Tech (11 dok., 47 pitanja) indeksiran i izmeren; UI deploy-ovan i isproban; RAGAS kod napisan (`evaluation/`), nije pusten** |

Trajno na nalogu stoje faze 1 i 2 — VPC, subnet-i, IGW, dva SG-a, dva gateway
endpointa, prazan S3 bucket, dve prazne DynamoDB tabele, i `RagModelServingStack`
sa ASG-om na **0/0** (launch template bez instance). Sve je besplatno ili se
placa po koriscenju kog nema, dakle ~0 USD/mesec.

### Faza 4 — pun integracioni prolaz (2026-09-26)

Ceo tok je prosao na prvi pokusaj: `SUCCEEDED`, `preparedChunks = indexedChunks
= 7`, zapis u `ingestion-log`. Redosled ovog puta: GPU prvi, search stack tek
kad se instanca pojavila — da se ne placa domen koji nema sta da radi.

| Korak | Vreme |
|---|---|
| ASG na 1 -> instanca (`g5.xlarge`, `1b`) | 8s, bez ijednog `InsufficientInstanceCapacity` |
| instanca -> `vllm-status=ready` | **13 min 39 s** (18:20:42Z -> 18:34:21Z) |
| `cdk deploy RagSearchStack` | 17.5 min, paralelno sa bootstrap-om |
| ceo ingestion tok | **15.7 s** |
| — Ekstrakcija / Map (2 slike, 4 VLM poziva) / Vektorizacija / Indeksiranje / Zavrsetak | 2.1 / 8.4 / 2.4 / 1.9 / 0.8 s |
| GPU ukupno upaljen | ~19 min |

**Pinovan bootstrap je prvi put proveren od nule** — do sada samo `--dry-run`.
Oba venv-a instalirana bez greske, straza `nvcc=13.0 torch.cuda=13.0`.

Embedding: 7 vektora, svi 1024 dim, nijedan chunk bez `sparse_weights`.

**Captioni — nalazi vazni za ablaciju:**

- Klasifikacija tacna u oba slucaja (`diagram`, `chart`).
- Grafikon: sve cetiri vrednosti TACNE (18.4, 21.8, 30.2, 27.9), ose i opseg
  tacni.
- Dijagram: svih 6 komponenti i tacan smer za 5 veza — ukljucujuci "metrike
  (push)" od cvorova KA Sovi, sto je bila namerna zamka. **Ali je izostavljena
  jedna veza: `Ruter particija -> Skladisni cvor A` ("upis").** Pitanje "kom
  cvoru ruter salje upis?" zato varijanta A ne moze da odgovori iz captiona, a
  varijanta B moze iz slike. To je upravo mehanizam koji ablacija meri — dobar
  konkretan primer za rad.
- **Captioni "odjekuju" prompt**: grafikon ponavlja naslove zahteva ("TACNE
  VREDNOSTI svake tacke...") i zavrsnu recenicu o necitljivim vrednostima.
  To je sum koji ulazi u embedding i BM25. Odluciti PRE finalnog korpusa: ili
  doterati prompt (trazi odgovor bez ponavljanja pitanja), ili prihvatiti i
  navesti. Promena prompta posle ingestion-a korpusa znaci ponovni ingestion.
- Sitna greska u prepisu ("Hljade" umesto "Hiljade").

### Faza 4 — delimicni integracioni prolaz (2026-09-24)

Deploy-ovani su `RagSearchStack` i `RagIngestionStack` (uz pinovan
`vllm-bootstrap.sh` na launch template-u). GPU instanca se NIJE podigla:
`g5.xlarge` je od 13:30Z do 14:10Z dobijao `InsufficientInstanceCapacity` u
sve tri zone. Tok je zato pusten bez GPU-a, i potvrdio je sve do captioning-a:

| Provera | Rezultat |
|---|---|
| EventBridge okidac | upload u `raw/` -> izvrsavanje za ~1s |
| `ExtractAndPrepare` (arm64, PyMuPDF) | 2s, 7 chunkova (4/1/2) — isto kao lokalno |
| DistributedMap | 5 ne-slika prosle, 2 slike pale — ocekivano |
| EC2 interface endpoint | `CaptionChunk` pao ODMAH sa `InferenceUnavailable`, ne na timeout-u |
| Format `Output` | `str` u `SUCCEEDED_0.json` — potvrdjuje potrebu za raspakivanjem |

Neprovereno ostaje ono sto trazi GPU: caption, embedding, bulk u indeks,
`ingestion-log`. Posle prolaza: ASG na 0, `RagSearchStack` srusen,
`RagIngestionStack` ostavljen (ne kosta nista dok miruje). U `raw/` i
`manifests/` su ostali artefakti prolaza; ponovni upload istog PDF-a ih
prepisuje (deterministicki `chunk_id`).

Faza 3 je 2026-09-18 deploy-ovana, proverena i srusena. Potvrdjeno je da
OpenSearch prihvata semu doslovno: `knn_vector` 1024 dim sa lucene HNSW
(`cosinesimil`, `ef_construction` 128, `m` 16) i `sparse_weights` kao
`rank_features`. Klaster je bio `green`. Ponovni `cdk deploy RagSearchStack`
vraca isto stanje za ~20 minuta.

### Faza 2 — rezultat validacionog prolaza (2026-09-18)

Oba modela rade na jednoj A10G kartici, sa komotnom rezervom:

| Mera | Vrednost |
|---|---|
| VRAM | **12549 MiB / 23028 MiB** |
| bge-m3 gusti vektor | 1024 dimenzije — poklapa se sa `knn_vector` u indeksu |
| bge-m3 retke tezine | rade (`/embed` vraca oba oblika) |
| Qwen2.5-VL caption nad dijagramom | tacno procitao komponente i smer strelice |
| Latencija generisanja | 2.5s za 120 tokena |

Latencija je vazna zbog tvrdog limita API Gateway-a od 29s: 2.5s ostavlja
dovoljno prostora za embedding i pretragu u istom zahtevu.

**Skripta je potvrdjena kao reproducibilna.** Drugi prolaz, sa ispravljenim
`vllm-bootstrap.sh` i bez ijedne rucne intervencije: instanca digla 13:58:24Z,
`vllm-status=ready` u 14:09:56Z — **11 minuta i 32 sekunde** od nule do oba
servisa. Straza za verzije je prijavila `nvcc=13.0 torch.cuda=13.0`.

To je razlika koja se lako previdi: prvi prolaz je dokazao da KONFIGURACIJA
radi, drugi da je AUTOMATIZACIJA reprodukuje. Za privatno hostovan sistem
vredi samo ovo drugo.

**Sest padova pre nego sto je proradilo.** Sveza `pip install vllm` na zvanicnom
Deep Learning AMI-ju ne radi bez intervencija u okruzenju. Redom:

1. `python3` je 3.12 bez `ensurepip` -> venv se ne pravi. Resenje: `python3.13`,
   kojim i DLAMI pravi `/opt/pytorch`.
2. `--limit-mm-per-prompt image=4` -> vLLM 0.29 provlaci vrednost kroz
   `json.loads`. Ispravno je `'{"image":4}'`.
3. flashinfer ne nalazi `nvcc` -> podrazumevano gleda `/usr/local/cuda`, kojeg nema.
4. `ninja` van `PATH`-a -> systemd daje minimalan `PATH` bez venv-a.
5. CCCL zaglavlja vs `nvcc` -> pip instalira nvcc **13.4** uz runtime zaglavlja
   **13.0**. CCCL trazi TACNO poklapanje. DLAMI-jev nvcc je 13.0 i slaze se sa
   `torch 2.13.0+cu130`.
6. `-lcudart` nenadjen -> build linkuje sa `-L$CUDA_HOME/lib64`, DLAMI drzi
   biblioteke u `lib/`. Resenje: simlink `lib64 -> lib`.

Zajednicki simptom bugova 3-6 je varljiv: vLLM se digne, **ucita model u VRAM**
(GPU pokaze ~10GB), pa padne na inicijalizaciji engine-a i GPU se vrati na nulu.
`systemctl is-active` pritom pokazuje `active`, jer `Restart=on-failure` odmah
dize novi pokusaj. Ne verovati tom izlazu — gledati `journalctl`.

**Pinovane verzije** (potvrdjene 2026-09-18, u `ec2-userdata/vllm-bootstrap.sh`):

| venv | paketi |
|---|---|
| `/opt/vllm-venv` | `vllm==0.29.0`, `torch==2.13.0`, `transformers==5.17.0`, `flashinfer-python==0.6.18` |
| `/opt/embed-venv` | `FlagEmbedding==1.4.2`, `torch==2.14.0`, `transformers==5.17.0`, `sentence-transformers==6.1.0` |

Dva venv-a traze **razlicit torch** (2.13.0 naspram 2.14.0). To nije propust nego
razlog zbog kog su razdvojeni — u zajednickom okruzenju jedan bi prepisao drugog.
Razresavanje oba skupa provereno `pip install --dry-run` na samoj instanci, bez
sukoba.

> **Verzije su pinovane.** Ne zato sto je drift izmeren — oba prolaza su vLLM-u
> dala isti `torch 2.13.0` — nego zato sto nepinovan `pip install` po definiciji
> ne garantuje isti rezultat sutra, a merenja u radu moraju biti ponovljiva.
> `pip install vllm` je vec dao kombinaciju paketa
> koja je sama sa sobom neusklađena (nvcc 13.4 + runtime 13.0). Merenja u radu
> moraju biti ponovljiva, a `latest` to po definiciji nije. Alternativa je
> zvanicni `vllm/vllm-openai` Docker image, koji dolazi sa uskladjenim CUDA
> lancem i ne kompajlira nista u letu.

### Faza 4 — odluke ugradjene u kod

- **Nema cross-stack reference ka `search-stack`-u.** Endpoint domena ide kroz
  SSM (`/rag/opensearch/endpoint`), a `IndexChunks` ga cita u vreme izvrsavanja.
  Cross-stack export bi napravio zavisnost koju CloudFormation postuje pri
  brisanju, pa `cdk destroy RagSearchStack` vise ne bi prolazio — cime bi propao
  razlog zbog kog je domen izdvojen.
- **`DistributedMap`, ne obicni `Map`.** Lista chunkova se cita iz S3 preko
  `ItemReader`-a. Obicni Map bi je nosio kroz stanje i probio tvrd limit Step
  Functions-a od **256KB** na prvom ozbiljnijem dokumentu.
- **Lambde su `arm64` (Graviton).** Razvojna masina je Apple Silicon, pa se x86
  paketi grade kroz emulaciju. PyMuPDF ima `manylinux2014_aarch64` wheel, pa
  nema gradnje iz izvora — a Graviton je uz to oko petine jeftiniji.
- **`_id` u OpenSearch-u je `chunk_id`.** Ponovni ingestion prepisuje dokumente
  umesto da ih duplira.
- **EventBridge pravilo je filtrirano na `raw/`.** Bez filtera bi manifesti i
  slike koje sam tok upisuje ponovo okidali ingestion, u beskonacnoj petlji.
- **Bulk vraca HTTP 200 i kad stavke ne prodju.** Greske su u telu, po stavci;
  `IndexChunks` ih izdvaja i dize glasno.
- **Interface endpointi za `ec2` i `ssm` su u `search-stack`-u** (uhvaceno
  pregledom pred integracioni prolaz, 2026-09-24). Lambde u VPC-u bez NAT-a
  vide samo gateway endpointe (S3, DynamoDB), a `find_inference_ip` zove
  `ec2:DescribeInstances`, `IndexChunks` zove `ssm:GetParameter` — oba bi
  visila do timeout-a. Interface endpoint se placa po satu (~0.012 USD/h po
  zoni), pa ne ide u `network-stack` nego zivi i rusi se zajedno sa domenom:
  bez domena ionako nijedan tok ne radi. Jedna zona (`1a`) je dovoljna.
- **DistributedMap pise `Output` kao JSON string**, ne objekat, u
  `SUCCEEDED_*.json`. `EmbedChunks` ga raspakuje (`outputs_from_result_file`).
- Testovi: `python3 -m unittest discover -s test/python` — 84 testa (posle faze 5: 120), bez
  ijedne instalacije (stdlib `unittest`, jer je lokalni Python 3.9).
- Test dokument: `corpus/generate_test_document.py` pravi
  `corpus/test/kestrel-prirucnik-test.pdf` (fiktivni "Kestrel", Vranac Sistemi).
- **Demo korpus** (2026-09-26, drugi): `corpus/demo/generate.py` pravi 11
  dokumenata (8 PDF, 3 DOCX) fiktivne softverske firme **Nexa Tech Solutions
  d.o.o.** i njenog SaaS proizvoda **Nexa Booking** (online zakazivanje
  termina): 7 tehnickih + 4 opsta (pravilnik o radu, organizacija i pozicije,
  finansijski izvestaj, politika bezbednosti — realniji korpus i "ometaci"
  pretrage). `pitanja.json`: 47 pitanja; 20 "samo na slici", od toga 4
  `tesko_za_opis`; 4 kroz dva dokumenta. Provera je uhvatila curenje odmah:
  "Tech lead" iz tabele pozicija je bio odgovor tehnickog pitanja "samo na
  slici" — uloga na CI/CD dijagramu je zato "release manager". Nazivi su IT-ovski
  (`booking-service`, "Payments team", "Message queue") — Lazar je odbio
  prethodnu temu ("Vranac Sistemi": Kestrel, Sova, Budilnik...) i izmisljene
  srpske nazive komponenti. Generator proverava da odgovor "samo na slici" ne
  postoji ni u jednom tekstu korpusa, pusta dokumente kroz pravi
  `extractor.py`, i brise stare izlaze (ceo `dokumenti/` ide u `raw/`).
- Nalazi o dijagramima (vizuelna provera): natpis preko kratke strelice
  sakrije njen smer; natpis izmedju dve kutije u redu prelazi preko njihovih
  ivica (vodoravni natpisi sad idu IZNAD kutija); strelica kroz natpis grupe
  moze da sakrije bas odgovor (natpis grupe moze uz donju ivicu, "dole").
  Lokalno kroz pravi `extractor.py` daje 7 chunkova: 4 tekst, 1 tabela,
  2 slike (dijagram arhitekture + stubicasti grafikon, za oba prompta).

### Prolaz sa korpusom Nexa Tech (2026-09-26, 21:00–22:00Z)

**Dva nova kvara, oba ispravljena:**

- **`IndexInit` pao 35 s posle `CREATE_COMPLETE` domena** — `SSL:
  UNEXPECTED_EOF_WHILE_READING`: domen prijavljen gotov, a endpoint jos ne
  prima TLS. CloudFormation je vratio ceo stack (rollback 14 min). Prva tri
  deploy-a su prosla slucajno. Ispravka: `_signed_request` ponavlja pri
  `OSError` sa rastucim razmakom (do ~4 min). Drugi deploy prosao.
- **bge-m3 servis pao sa SIGSEGV** kad je 11 ingestion tokova istovremeno
  stiglo do embedding-a (`Connection reset by peer` u `EmbedChunks`). FastAPI
  `def` endpoint-i rade u vise niti, a model na GPU-u nije bezbedan za
  paralelne pozive. Ispravka u `vllm-bootstrap.sh`: `threading.Lock` oko
  `model.encode`. **Napisano, NIJE deploy-ovano** (trazi deploy
  `RagModelServingStack` + novu instancu). Do tada: dokumente ubacivati
  jedan po jedan (tako je ovaj prolaz zavrsen: 11/11 za <2 min, 60 chunkova).

**Rezultat, 47 pitanja x A/B** (`evalRunId=demo-nexa-2026-09-26`, rucno
ocenjeno — automatska ocena po kljucnim recima opet je potcenila):

| Skup | A | B |
|---|---|---|
| sva pitanja (47) | 33 | 35 |
| samo na slici (20) | 10 | **13** |
| od toga tesko za opis (4) | 1 | 1 |
| tekst/tabela/vise dokumenata (27) | 23 | 22 |

Retrieval: pravi dokument u top-5 za **47/47**; slika u top-5 za 19/20
pitanja "samo na slici" (vs. stari korpus sa test PDF-om: vise promasaja).

**Glavni nalaz za rad — prednost B nije tamo gde je ocekivana:**

- B je pobedio na A4, N3 (grafikoni: "najveca vrednost") i H4 (dijagram
  odobravanja). **U sva tri slucaja caption je bio TACAN** ("POST /payments:
  468", "jun: 529", "Team lead -> Department head"), a A je pogresio u
  ZAKLJUCIVANJU (izabrao pogresan maksimum, pogresnu granu). Slika je
  pomogla generatoru da rezonuje, ne da dobije podatak koji fali.
- Na "tesko za opis" pitanjima (pripadnost namespace-u K3/K4, strelica bez
  natpisa F3) caption jeste propustio cinjenicu — ali ni B sa slikom nije
  uspeo: 7B VLM ne cita pripadnost grupi ni neoznacenu strelicu. O3
  (kancelarija) su oba resila. Ogranicenje modela, ne arhitekture.
- Caption kvalitet varira po dijagramu: na arhitekturi i Kubernetes-u su
  izmisljeni natpisi i obrnuti smerovi (npr. "api-gateway -> PostgreSQL:
  event"); na jednostavnim tokovima (pravilnik, bezbednost) tacan.
- Ostali promasaji: C3 (slika nije u top-5), X1/X3/X4 (pitanja kroz dva
  dokumenta — model izmislja uzrok ili odustaje), H1 (racun: 30 umesto 24,
  uzeo "najvise 30"), O4 (obrnut odnos CEO/Head of People).

### Greska u promptu: pogresno navodjenje izvora (nadjeno 2026-10-02) — ISPRAVLJENO I DEPLOY-OVANO

Pregledom `mm_faithfulness` (0 uz tacan odgovor) iz `eval-2026-10-01`: od 86
navedenih izvora 38 pogresno (A i B podjednako), od toga 31 tacno +1. Uzrok:
chat template Qwen2.5-VL spaja tekstualne delove poruke BEZ razmaka, pa je kraj
teksta izvora n bio zalepljen za `[n+1] (zaglavlje)` — potvrdjeno renderovanjem
pravog `chat_template.json`. Ispravka u `prompting.py`: svaki deo zavrsava sa
`\n\n`; u B slika ide IZMEDJU zaglavlja i captiona (unutar bloka izvora);
`PROMPT_FORMAT = 2` ulazi u `prompt_fingerprint` (stari zapisi imaju drugi
otisak). U `ragas_eval.py` slike idu NA KRAJ konteksta (RAGAS sam numerise
"Context n", slika izmedju bi pomerila numeraciju). Testovi: 157. Rad: 5.6.2 i
nova 5.8.4. **Trazi deploy `RagQueryStack` pre sledeceg merenja.** Rezultati
`eval-2026-10-01` su sa starim promptom (A/B i dalje fer, isti prompt u obe);
`answer_accuracy` i `faithfulness` ne zavise od brojeva izvora, `mm_faithfulness`
zavisi.

### Drugo merenje (2026-10-02) — prosireni korpus, ispravljen prompt

GPU: rezervni `g5.2xlarge` (1b) dobijen za 32 s — PRVI put; pinovan bootstrap
prosao i na njemu, `ready` za 10.5 min. 22 dokumenta, 109/109 delova za ~80 s.
Tri prolaza (svi u query-log-u i lokalno u `evaluation/results/`):

| Prolaz | prompt (otisak) | pogresni navodi | bez navoda |
|---|---|---|---|
| eval-2026-10-01 (stari korpus) | stari format (d474d66c226b) | 44% | 1/94 |
| **eval-2026-10-02 (GLAVNO)** | razdvojeni izvori + "npr. [2]" (986c82675573) | 21% | 4/212 |
| eval-2026-10-02b (provera) | bez primera (a50a1008f6ed) | 15% | 88/212 |

Ostatak gresaka u 02: 27 od 38 pogresnih navoda je [2], pravi izvor [1] -> model
prepisuje primer. Bez primera manje gresaka, ali 42% odgovora bez navoda; TACNOST
ista (odgovor sadrzi dokaz: A 64/65, B 70/69). Odluka: glavno = 02, 02b =
provera robusnosti, prompt vracen na 02 (otisak proveren) i deploy-ovan; prompt
se dalje NE podesava na istom skupu pitanja (prilagodjavanje skupu za evaluaciju).
Uz oba: `-sparse` prolazi (106, samo A). GPU i RagSearchStack OSTAVLJENI UPALJENI
(Lazar hoce rucnu proveru) — gasiti samo uz njegovu potvrdu.

### Prosirenje korpusa (2026-10-01, posle prvog merenja) — indeksirano 2026-10-02

22 dokumenta (bilo 11), 109 delova (60 tekst / 21 tabela / 28 slika), 106
pitanja (bilo 47): 56 "samo na slici" (bilo 20), 15 teskih (bilo 4), 7 kroz
dva dokumenta. Novo u `corpus/demo/documents_dodatni.py` i
`questions_dodatna.py`; crtac (`render.py`) dobio dijagram sekvence,
multiline (bez ispisanih vrednosti), grupisane stubice, tortu i Gantt.
Ometaci: `booking-arhitektura-2-2`, `sla-i-podrska-2025` -> pitanja A1, A4,
S1, S2 dobila precizniji tekst (`izmene_postojecih`). Nova oznaka
`naziv_i_u_tekstu` (odgovor je naziv iz teksta, a cinjenica samo na slici;
preskace proveru curenja, trazi `napomena`). Provera curenja je uhvatila dva
slucaja (zaglavlje "Pravna sluzba" u novom dokumentu = odgovor B3; "2.4" =
broj verzije) — ispravljeno. Sve nove slike vizuelno proverene (dve
ispravljene: strelica kroz kutiju). Stari dokumenti su regenerisani (isti
sadrzaj, drugaciji bajtovi). Za merenje: svih 22 u `raw/`, pa novi `RUN`.

### Evaluacija — prvi pun prolaz (2026-10-01, `eval-2026-10-01`)

Sesija: deploy `RagStorageStack` (`retainData: true`; auto-delete handler
proverava tag `aws-cdk:auto-delete-objects`, pa nije praznio bucket —
provereno) i `RagModelServingStack` (bge-m3 lock). GPU: 5 min
`InsufficientInstanceCapacity` (1a, 1c; rezervni `g5.2xlarge` se u porukama
nije pojavio), pa `g5.xlarge` u 1b; `ready` za 12.5 min; ukupno upaljen 22 min.
`RagSearchStack` deploy 18 min, destroy 15.5 min. Svih 11 dokumenata
istovremeno za ~25 s, 60/60 delova — **lock radi** (ranije SIGSEGV).
94/94 odgovora (~0.9 s prosek); plus `eval-2026-10-01-sparse` (47, samo A).
Rezultati su LOKALNO u `evaluation/results/` (nije na git-u) i u query-log-u.

| Sudija Claude (AnswerAccuracy >= 0.75) | A | B | samo A | samo B | p tacan |
|---|---|---|---|---|---|
| sva (47) | 33 | 38 | 0 | 5 | 0.0625 |
| samo na slici (20) | 10 | 15 | 0 | 5 | 0.0625 |
| tekst/tabela/vise (27) | 23 | 23 | 0 | 0 | 1 |

B pobedjuje na A3, A4, H4, N3, S3 (A4/N3/H4 isto kao rucna ocena 26.9).
**Sa 5 neslaganja tacan test ne moze ispod 0.0625 ni kad su sva u korist B**
-> skup pitanja "samo na slici" je premali; dopuna je prioritet.
Pretraga: Hit@5 0.98, MRR 0.85 (samo na slici 0.68); sa sparse MRR 0.88/0.71.
Otvoreno: `mm_faithfulness` nize od `faithfulness` i na tekstu (0.78 vs 0.95;
binarna je strozija) — pregledati obrazlozenja sudije (npr. X4 A: 1 vs 0)
pre upotrebe u radu. `manual.csv` prazan — ko ga popunjava, nije odluceno.

### Faze 4+5 — integracioni prolaz sa demo korpusom (2026-09-26, uvece)

GPU `g5.xlarge` u `1b` odmah; `ready` za ~12 min; ukupno upaljen 26 min.

| Provera | Rezultat |
|---|---|
| search pipeline-i (oba) | prihvaceni na domenu (`IndexInit`, `schemaVersion` 2) |
| `neural_sparse` + `query_tokens` | **radi** na OpenSearch 2.19 |
| 16 smoke upita (4 pitanja x A/B x 2 oblika pretrage) | svi 200, 0.5–2.8 s |
| API Gateway | bez kljuca 403, sa kljucem 200 za 0.8 s |
| demo korpus (7 dok., 2 DOCX) + test PDF | 8/8 `SUCCEEDED`, `indexed == prepared` — **prvi put DOCX na AWS-u** |
| 28 pitanja x A/B (`evalRunId=demo-vranac-2026-09-26`) | rucno ocenjeno: **A 24/28, B 25/28** |

**Nadjeno i ispravljeno u toku prolaza:**

- **Caption je posle sablona prepisivao blok "Pravila:"** (odjek prompta,
  samo pomeren). Pravila su sad PRE sablona, a `clean_caption` odseca sve od
  reda "Pravila:". Potvrdjeno: captioni cisti, i svih 6 strelica dijagrama
  test dokumenta je tu (ukljucujuci ranije izostavljenu `Ruter -> Cvor A`).
- **Lambda konkurentnost naloga je 10** (`L-B99A9384`). Osam dokumenata
  odjednom x Map od 4 -> dva toka pala sa `Lambda.TooManyRequestsException`
  (429). Svi koraci toka sad imaju retry na tu gresku (eksponencijalno, sa
  jitter-om); potvrdjeno ponovnim pustanjem. Povecanje kvote je besplatno i
  vredi ga traziti pre evaluacije.

**Nalazi vazni za rad i evaluaciju:**

- **Na pitanjima "samo na slici" A i B su izjednaceni (8/10 oba).** Doterani
  captioni sada nose te cinjenice, pa B nema gde da pokaze prednost. Prednost
  B se ocekuje tek na detaljima koje caption ne zapise — M3 (u kojoj zoni je
  cvor-svedok): caption navodi zone, ali ne i pripadnost, i uz to je pogresio
  smerove strelica bez natpisa. Evaluacioni skup treba dopuniti takvim
  pitanjima (prostorni odnosi, pripadnost grupi, strelice bez natpisa).
  Ovo iskreno navesti u radu: dobar caption smanjuje razliku A/B.
- **Promasaji su vecinom RETRIEVAL, ne generator:** S3 (dijagram sa
  "Postar" nije u top-5), X1 (tabela Sove nije vracena; model je onda
  izmislio da Sova proziva cvorove — suprotno izvoru).
- **Test dokument zagadjuje demo korpus** (nalaz sa STARIM korpusom "Vranac
  Sistemi", zamenjenim istog dana). `kestrel-prirucnik-test` opisuje
  isti izmisljeni sistem drugim podacima ("zona eu-1" naspram "Nis-1"); u M3 i
  X1 je bas on bio visoko rangiran. Za demo i evaluaciju indeksirati SAMO
  `corpus/vranac/dokumenti/`; test PDF iz `raw/` ukloniti.
- **Prisustvo slike menja odgovor i na tekstualnom pitanju:** M2 — isti tekst
  u kontekstu, A kaze "nije pronadjeno", B odgovara tacno.
- **Pitanja moraju biti sa dijakriticima i jasne forme.** Bez dijakritika, i
  sa "Kom ...", model odgovara "Da/Ne" ili pogresno.
- **Automatska ocena po kljucnim recima je nepouzdana** (padezi, parafraze):
  od 10 automatskih "promasaja" 6 su bili tacni odgovori. Argument vise za
  LLM sudiju u RAGAS-u.

### Faza 6 — UI (2026-09-26, deploy-ovano uz `RagQueryStack`)

`ui/` (index.html, style.css, app.js) — staticka stranica, bez biblioteka i
bez build koraka. Hostuje je `RagQueryStack` na S3 website hosting-u.

- **Zaseban JAVNI bucket** za stranicu; bucket sa podacima ostaje privatan.
  Pravilo "jedan bucket" vazi za podatke. Account-level Block Public Access
  nije postavljen (provereno), pa javna bucket politika prolazi.
- **API kljuc NIJE u stranici** — unosi se u "Podesavanja veze" i cuva u
  localStorage. `config.json` (adresa API-ja) i `pitanja.json` (primeri sa
  ocekivanim odgovorom) postavlja `BucketDeployment` pri deploy-u.
- **"Uporedi A i B"** salje oba zahteva paralelno i prikazuje ih jedan pored
  drugog — glavni prikaz ablacije na prezentaciji.
- Izvori: tip, dokument, strana, skor, pocetak teksta, i originalna slika
  preko **presigned linka** (15 min) koji vraca Lambda (`public_sources`).
  Slika se prikazuje odmah SAMO ako ju je generator stvarno video
  (`sentToGenerator`); u A je iza linka "generator je nije video".
- `[n]` u odgovoru je link ka izvoru n. Tekst modela ide iskljucivo kroz
  `textContent` (nepoverljiv ulaz).
- API Gateway greske (403 bez kljuca, 504 posle 29 s) dobile su CORS
  zaglavlja (`addGatewayResponse`), da UI prikaze pravu poruku.
- Provereno lokalno (lazni API), pa **na zivom API-ju 2026-09-26 u 20:30Z**:
  indeksiran SAMO demo korpus (7/7, 43 chunka, sva istovremeno — retry na
  429 radi), pa "Uporedi A i B" nad M3 (zona cvora-svedoka): **A netacno
  ("Nis-1"), B tacno ("Kragujevac-1")** — caption navodi zone ali ne i
  pripadnost, a B vidi sliku. Bez test dokumenta u indeksu razlika A/B se
  pokazala tacno gde je ocekivana. Najbolji primer za prezentaciju.
- Adresa stranice: izlaz `UiUrl` stack-a `RagQueryStack` (HTTP, S3 website).
  Adrese namerno nisu upisane ovde — repo je javan.
- **Brz pad kad je sve ugaseno.** Bez search stack-a nema ni EC2 interface
  endpoint-a, pa je `DescribeInstances` visio do timeout-a: API je vracao 504
  posle 29 s, sto izgleda kao spor model. `lambda/common/inference.py` sada
  ima kratke timeout-e i vraca 503 sa porukom "da li su podignuti GPU i
  RagSearchStack?" za ~10 s. Layer je izmenjen, a `RagIngestionStack` jos
  nije redeploy-ovan sa njim (nije hitno: tamo ionako pada Step Functions).

### Faza 5 — odluke ugradjene u kod (2026-09-26)

- **Dva search pipeline-a**, jer normalization processor trazi tacno onoliko
  tezina koliko upit ima podupita: `rag-hybrid-dense-bm25` (osnovna pretraga)
  i `rag-hybrid-dense-bm25-sparse` (sekundarni eksperiment). Min-max
  normalizacija, JEDNAKE tezine — namerno neutralno; podesavanje tezina bi
  bilo zaseban eksperiment. Pravi ih `IndexInit` (`schemaVersion` 2).
  Redosled podupita (BM25, kNN, sparse) i broj tezina zakljucani su testom
  koji poredi `index_init/pipelines.py` i `query_handler/retrieval.py`.
- **Retka grana je `neural_sparse` sa `query_tokens`**, ne zbir `rank_feature`
  upita sa `linear` funkcijom (`linear` je u ES dodat posle forka OpenSearch-a).
  **Neprovereno na domenu** — prva stvar za integracioni prolaz.
- **Tekst prompta je IDENTICAN u A i B**; B samo dodaje originalnu sliku odmah
  posle njenog captiona. Sistemski prompt zato ne pominje slike. Zakljucano
  testom (`text_only(A) == text_only(B)`).
- **Najvise 4 slike u B** (`--limit-mm-per-prompt {"image":4}`), prve po
  rangu; koje su stvarno poslate pise u `attachedImages` u `query-log`-u.
- **`query-log` cuva sve sto bilo koji RAGAS sudija trazi** (pitanje, tacno
  one kontekste koje je generator video, odgovor) plus uslove merenja
  (varijanta, oblik pretrage, k, model, pipeline, `promptFingerprint` —
  sha256 sistemskog prompta, 12 znakova). **Neuspesni upiti se takodje
  upisuju**, sa `error` — bez njih bi procenat uspeha izgledao bolji.
  `evalRunId` se izostavlja kad ga nema, pa GSI `byEvalRun` sadrzi samo
  evaluaciona pitanja.
- **Lambda timeout 60s, API Gateway 29s.** Evaluaciona skripta zove Lambdu
  DIREKTNO (izlaz `QueryFunctionName`) i zaobilazi limit od 29s; preko API-ja
  klijent posle 29s dobija 504, ali se zapis svejedno upise.
- **API kljuc + usage plan** (5 req/s, 2000/dan): endpoint je javan, a iza
  njega je jedna GPU instanca. Vrednost kljuca nije u izlazu stack-a — vidi
  izlaz `ApiKeyCommand`.
- `QueryStack` ima sopstvenu kopiju `common` layer-a (isti izvorni
  direktorijum), da ne bi imao cross-stack zavisnost od `ingestion-stack`-a.
- Testovi: 120 (sa 36 novih za fazu 5). Synth bez Docker-a (samo za proveru
  template-a): `npx cdk synth RagNetworkStack -e --output <dir>` — CDK tada
  pise template-e svih stack-ova, a pakuje samo izabrani.

### Kvote (resen blokator)

GPU kvota je **odobrena 2026-09-18**: `L-DB2E81BA` (Running On-Demand G and VT
instances) je sada **8 vCPU**, potvrdjeno i preko API-ja, ne samo u mejlu.
`g5.xlarge` je 4 vCPU, a rezervni `g5.2xlarge` 8 vCPU — staje po jedna, sto
ASG sa `maxCapacity: 1` ionako trazi.

**Ispravka na raniju dokumentaciju:** kvota za standardne instance
(`L-1216C47A`) nije 5 vCPU nego **32**. Time otpada i potreba za zaobilaznicom
preko CPU embedding servera — na 24GB staju oba modela zajedno, kako dizajn i
predvidja.

```bash
aws service-quotas get-service-quota --service-code ec2 \
  --quota-code L-DB2E81BA --region eu-central-1 --profile lazar-private \
  --query "Quota.Value" --output text
```

## Sledeci korak

Faza 4 je zavrsena. Pred fazu 5 su bile tri odluke:

1. ~~`sparse_weights`~~ — **odluceno** (vidi "Serving sloj"): sekundarni
   eksperiment, osnovna pretraga dense+BM25. `QueryHandler` treba parametar
   koji bira izmedju dva oblika upita.
2. **Sudija za RAGAS — ODLUCENO 2026-10-01: SAMO Claude** (Sonnet 5, preko
   Anthropic-ovog OpenAI-kompatibilnog API-ja; Lazar odbio drugog sudiju).
   Qwen nije sudija: ocenjivao bi sopstvene odgovore (odeljak 2.5.3 rada).
   Obrazlozenje za rad: privatnost se odnosi na SISTEM (put pitanje ->
   odgovor ostaje privatan); sudija je merni instrument van sistema, a korpus
   je sinteticki. Rucna ocena je zlatni standard; sudija se poredi sa njom (kapa).
3. ~~Captioning prompt~~ — **prepisan u kodu (2026-09-26), NEPROVEREN na GPU-u.**
   Uputstva odvojena od oblika odgovora (sablon sa poljima `Komponente:`,
   `Veze:`, `Vrednosti:`...), izricito "bez ponavljanja ovih uputstava", i za
   dijagram "jedna stavka po strelici" uz zavrsnu proveru. U sledecem GPU
   prolazu ponovo pustiti test PDF i proveriti: nema odjeka prompta, i
   `Ruter particija -> Skladisni cvor A` vise ne fali.

Faze 4 i 5 su provereni end-to-end. Sledece, redom:

1. **Novi korpus kroz sistem** (`corpus/demo/dokumenti/`) i `pitanja.json`
   kroz A/B (trazi GPU + search, UZ POTVRDU). Iz `raw/` pre toga ukloniti
   stari korpus (Vranac) i test PDF. [staro:] Ukloniti test PDF iz `raw/`, da ne ulazi
   u indeks demo korpusa.
2. **Zatraziti povecanje Lambda konkurentnosti** (`L-B99A9384`, sada 10).
3. **Retrieval**: S3 i X1 su promasaji pretrage. Kandidati: veci `k` (8),
   ili naslov dokumenta ispred teksta chunka pri embedding-u (kontekst
   chunka). Meriti, ne pogadjati — `pitanja.json` je vec merni skup.
4. **Dopuniti pitanja** onima na kojima se ocekuje prednost B (vidi nalaze).
5. **Evaluacija — kod NAPISAN (2026-10-01), NIJE pusten.** `evaluation/`
   (vidi `evaluation/README.md`): `run_queries.py` -> `fetch_log.py` ->
   `ragas_eval.py` -> `report.py`. RAGAS 0.4.3. Metrike:
   Hit@k/MRR, `faithfulness` (tekst) + `mm_faithfulness` (sudija vidi i slike
   — inace bi B bio kaznjen za tvrdnje sa slike), `answer_accuracy`,
   `context_recall`; McNemar tacan oblik. **Sudija proveren probnim pozivom
   (2026-10-01)** na 3 izmisljena primera: tacan iz teksta -> sve 1; odgovor
   SA SLIKE -> faithfulness 0 ali mm_faithfulness 1 (potvrda zasto dve
   vernosti); izmisljen -> 0. Kvake Anthropic OpenAI-compat sloja: odbija
   `json_object` i `json_schema` bez `strict` -> instructor `Mode.MD_JSON`;
   Sonnet 5 odbija `temperature` -> ne salje se (ponovljivost daje kes sudije).
   Kljuc je u `evaluation/config.json` (u .gitignore-u). Pre pustanja jos:
   (a) deploy bge-m3 lock-a (`RagModelServingStack`, uz potvrdu),
   (b) `retainData: true` u `bin/app.ts`, (c) ko popunjava `manual.csv`.
6. ~~UI~~ — deploy-ovan i isproban na zivom API-ju (2026-09-26).

Obrazac za svaki prolaz sa GPU-om: **ASG prvi, search stack tek kad se
instanca pojavi; posle provere ASG na 0 odmah, pa `cdk destroy RagSearchStack`.**

## Poznati rizici

- Deep Learning AMI: stvarno ime je `Deep Learning OSS Nvidia Driver AMI GPU
  PyTorch * (Ubuntu 24.04)`. Pattern `Deep Learning AMI GPU PyTorch*` iz ranije
  dokumentacije **nece naci nista** — provereno, vraca nula slika. U kodu se
  AMI uzima preko javnog SSM parametra
  `/aws/service/deeplearning/ami/x86_64/oss-nvidia-driver-gpu-pytorch-2.12-ubuntu-24.04/latest/ami-id`,
  a ne preko `MachineImage.lookup`, jer bi lookup zakucao AMI ID u
  `cdk.context.json` koji je u `.gitignore`-u.
- **GPU kapacitet je po zoni, i menja se iz sata u sat.** `g5.xlarge` je
  2026-09-18 pao sa `InsufficientInstanceCapacity` u `eu-central-1a`, dok ga je
  AWS nudio u `1b` i `1c`. Zato VPC ima `maxAzs: 3` iako sistem koristi jednu
  instancu — da ASG ima gde da pokusa. Prazni public subnet-i ne kostaju nista.
  Paznja: `describe-instance-type-offerings` pokazuje da tip POSTOJI u zoni, ne
  da ima slobodnog kapaciteta; te dve stvari se lako pomesaju.
- **Kvota nije kapacitet.** 2026-09-24 `g5.xlarge` nije bilo ni u jednoj zoni
  40 minuta. "Spot placement score" za `g5.xlarge` je u celoj Evropi 1-3 od 10
  (Frankfurt 3, najbolji) — selidba regiona ne pomaze. Ublazavanje: rezervni
  `g5.2xlarge` u ASG-u; za finalnu RAGAS evaluaciju On-Demand Capacity
  Reservation cim se instanca dobije (placa se i kad miruje — samo za prozor
  evaluacije). ASG posle niza neuspeha sam uspori pokusaje na ~2 min.
  Vredi pasus u poglavlju o ogranicenjima: privatno hostovan sistem na javnom
  oblaku nosi rizik dostupnosti koji API servis nema.
- **`cdk destroy RagSearchStack` traje 15-45 min, promenljivo** (2026-09-24:
  ~40 min, 2026-09-26: 15.5 min). `IndexInitFunction`
  je Lambda u VPC-u; AWS njen ENI oslobadja asinhrono (do ~40 min), a domen se
  brise tek posle nje (funkcija zavisi od endpoint-a domena). Za to vreme
  domen i dalje radi i naplacuje se. Ne brisati ENI rucno — rizik je
  `DELETE_FAILED`.
- **`cdk.out` zakljucava paralelne CDK komande.** Dok radi `deploy`/`destroy`,
  `cdk diff` pada; koristiti `--output <drugi-dir>`.
- **Dodavanje zona trazi deploy OBA stack-a.** `VPCZoneIdentifier` na ASG-u je
  fiksna lista subnet ID-jeva, pa `RagNetworkStack` pravi nove subnet-e, ali ih
  ASG pokupi tek kad se i `RagModelServingStack` ponovo deploy-uje.
- **Dva vLLM procesa na istoj kartici:** vLLM podrazumevano uzme ~90% VRAM-a.
  Bez eksplicitnog `--gpu-memory-utilization` prvi proces pojede sve i drugi ne
  startuje. U `vllm-bootstrap.sh` je ograniceno na 0.62 za Qwen, ostatak ide
  bge-m3 i rezervi.
- **Lambda u VPC-u nema internet.** Nema NAT-a, a Lambda ENI ne dobija javnu IP
  ni u public subnet-u. Zato u `network-stack`-u postoje gateway endpointi za
  S3 i DynamoDB (besplatni), a svaka Lambda u VPC-u mora imati
  `allowPublicSubnet: true` — inace CDK odbija synth. Preko S3 endpoint-a ide i
  odgovor CloudFormation custom resource-a; bez njega deploy ne pukne nego
  **visi do timeout-a**.
- **Opisi SG pravila imaju ogranicen skup znakova:**
  `a-zA-Z0-9. _-:/()#,@[]+=&;{}!$*`. Znak `>` nije dozvoljen, pa `->` u opisu
  rusi stack tek u `CREATE` fazi — `cdk synth` i `cdk diff` to ne uhvate.
- vLLM cold start (ucitavanje 7B modela u VRAM) traje desetine sekundi do par
  minuta — ne testirati cim EC2 predje u "running", cekati `/health`.
- bge-m3 nema potvrdenu validaciju za srpski u zvanicnim benchmarcima
  (MIRACL/MKQA). Deklarisana je podrska za "100+ jezika", ali ne tvrditi
  "dokazano najbolji za srpski" bez sopstvene empirijske provere.
- `cdk destroy --all` brise i S3 bucket sa podacima. Pre finalne evaluacije
  postaviti `retainData: true` u `bin/app.ts`.
