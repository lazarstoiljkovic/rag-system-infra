# rag-system-infra

AWS CDK infrastruktura za privatno hostovani RAG sistem nad tehnickom
dokumentacijom — prakticni deo diplomskog rada.

Kontekst, arhitektonske odluke i stanje implementacije: [CLAUDE.md](CLAUDE.md).

## Preduslovi

- Node 22 (`nvm use` cita `.nvmrc`)
- Docker pokrenut lokalno (za `PythonFunction` packaging)
- AWS profil `lazar-private`

```bash
export AWS_PROFILE=lazar-private
nvm use
npm install
```

## Stack-ovi

| Stack | Sadrzaj |
|---|---|
| `RagNetworkStack` | VPC (1 AZ, bez NAT-a), security groups |
| `RagStorageStack` | S3 bucket (`raw/`, `images/`, `eval/`), 2 DynamoDB tabele |
| `RagModelServingStack` | ASG min=0/max=1, g5.xlarge, vLLM |
| `RagIngestionStack` | Step Functions + 5 Lambdi |
| `RagQueryStack` | API Gateway + QueryHandler |
| `RagObservabilityStack` | CloudWatch dashboardi (opciono) |

## Deploy

Redosled nije proizvoljan — model-serving se rucno proverava pre nego sto se
gradi bilo sta iznad njega.

```bash
npx cdk diff  RagNetworkStack
npx cdk deploy RagNetworkStack -c developerCidr=<tvoja-ip>/32   # ne upisivati u cdk.json
npx cdk deploy RagStorageStack

npx cdk deploy RagModelServingStack
# --- STANI: rucno proveri da vLLM radi pre nego sto nastavis ---

npx cdk deploy RagIngestionStack
npx cdk deploy RagQueryStack
```

## GPU instanca

Pali se i gasi rucno — nema auto-stop automatizacije.

```bash
aws autoscaling set-desired-capacity --auto-scaling-group-name <asg> --desired-capacity 1
aws autoscaling set-desired-capacity --auto-scaling-group-name <asg> --desired-capacity 0
```
