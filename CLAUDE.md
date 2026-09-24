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

> **Otvoreno pitanje za fazu 5.** Retriever je specificiran kao "dense + BM25",
> sto znaci da se `sparse_weights` puni ali se ne pretrazuje. Ili ga treba
> ukljuciti u hibridni upit, ili ga izbaciti iz seme da ne stoji kao mrtav
> podatak. Odluka nosi jedan pasus opravdanja u radu, pa je ne preskakati.

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
| 4 | `ingestion-stack` | **napisano, nije deploy-ovano** |
| 5 | `query-stack` | nije poceto |
| 6 | korpus, RAGAS, UI | nije poceto |

Faza 1 je jedino sto trajno stoji na nalogu — VPC, subnet, IGW, dva SG-a, dva
gateway endpointa, prazan S3 bucket i dve prazne DynamoDB tabele. Sve je
besplatno ili se placa po koriscenju kog nema, dakle ~0 USD/mesec.

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
- Testovi: `python3 -m unittest discover -s test/python` — 78 testova, bez
  ijedne instalacije (stdlib `unittest`, jer je lokalni Python 3.9).

### Kvote (resen blokator)

GPU kvota je **odobrena 2026-09-18**: `L-DB2E81BA` (Running On-Demand G and VT
instances) je sada **8 vCPU**, potvrdjeno i preko API-ja, ne samo u mejlu.
`g5.xlarge` je 4 vCPU, dakle staje jedna instanca komotno. Dostupna je u
`eu-central-1a`, gde nam je i jedini subnet.

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

Faza 2 je napisana i ceka jedan validacioni prolaz. Redosled je namerno takav
da se najskuplja nepoznanica proveri pre nego sto se na njoj sagradi faza 4.

1. `cdk deploy RagModelServingStack`, pa rucno dizanje ASG-a na 1. Potvrditi da
   oba modela stanu na karticu, da `/health` odgovori na 8000 i 8001, i da se
   instanca sama tagovala `vllm-status=ready`. Zatim odmah spustiti na 0.
2. Faza 4 — `ingestion-stack`. Veci deo (`ExtractAndPrepare`, chunking,
   serijalizacija tabela, skelet Step Functions toka) pise se i testira lokalno,
   bez ijednog pokrenutog resursa.
3. Integracioni prolaz faze 4: dici `RagSearchStack` i GPU zajedno, provuci
   test korpus, potvrditi dokumente u indeksu, pa sve spustiti.

Obrazac koji se pokazao dobro: **napisi besplatno, pusti jednom, proveri,
srusi.** Na `search-stack`-u je kostao oko 3 centa.

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
