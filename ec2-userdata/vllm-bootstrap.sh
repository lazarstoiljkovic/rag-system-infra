#!/bin/bash
set -euxo pipefail
# user-data za GPU instancu (faza 2).
#
# Pokrece dva servisa:
#   :8000  vLLM, Qwen2.5-VL-7B-Instruct-AWQ — captioning I generisanje
#   :8001  bge-m3 embedding (dense + sparse)
#
# Na kraju, tek kad oba /health endpointa odgovore, instanca se taguje
# vllm-status=ready — Lambda funkcije ne smeju da je koriste pre toga.
#
# Ceo izlaz ide u /var/log/vllm-bootstrap.log. Pri dijagnostici prvo tamo
# gledati, jer se user-data greske ne vide u konzoli instance.

exec > >(tee -a /var/log/vllm-bootstrap.log) 2>&1
echo "bootstrap poceo: $(date -Is)"

MODELS_DIR=/opt/models
# Dva odvojena venv-a, namerno. vLLM pinuje tacnu verziju PyTorch-a, a
# FlagEmbedding povlaci svoj transformers i sentence-transformers. U istom
# okruzenju to je sukob koji se ispolji tek posle ~20 minuta skidanja, pa se
# izolacija isplati vise od ustedjenog prostora na disku.
VLLM_VENV=/opt/vllm-venv
EMBED_VENV=/opt/embed-venv
export HF_HOME="$MODELS_DIR"

mkdir -p "$MODELS_DIR"

# ---------------------------------------------------------------------------
# Raspodela VRAM-a na 24GB (A10G)
#
# Dva odvojena procesa dele istu karticu, pa vLLM-u MORA da se ogranici apetit.
# Podrazumevano uzima ~90% VRAM-a za sebe (tezine + KV cache) i drugi proces
# onda ne moze da se pokrene. Ovo je najcesci uzrok "radi mi lokalno" kvara.
#
#   vLLM (Qwen2.5-VL-7B AWQ):  0.62 * 24GB ~ 14.9GB  (tezine ~5GB + KV cache)
#   bge-m3 (fp16):                          ~4GB     (tezine ~2.3GB + aktivacije)
#   rezerva:                                ~3GB     (CUDA konteksti, fragmentacija)
# ---------------------------------------------------------------------------
VLLM_GPU_FRACTION=0.62

# DLAMI vec nosi NVIDIA drajver i CUDA. Oba venv-a idu odvojeno od sistemskog
# PyTorch-a koji dolazi uz AMI, da ga ne prepisu.
#
# hf_transfer osetno ubrzava skidanje tezina. Sa ASG min=0/max=1 svaka nova
# instanca skida modele iznova (~8GB), pa ovo nije sitnica.
export HF_HUB_ENABLE_HF_TRANSFER=1

# Sistemski `python3` na ovom AMI-ju je 3.12 i NEMA ensurepip, pa `python3 -m
# venv` puca sa "ensurepip is not available". Python 3.13 ga ima — DLAMI i sam
# njime pravi /opt/pytorch. Zato 3.13, uz apt fallback ako ga nekad ne bude.
PY=/usr/bin/python3.13
if ! "$PY" -m venv --help >/dev/null 2>&1; then
  echo "python3.13 bez venv modula, padam na apt"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv
  PY=/usr/bin/python3
fi
echo "venv se pravi sa: $PY ($($PY --version))"

# ---------------------------------------------------------------------------
# PINOVANE VERZIJE — ne dirati bez ponovnog validacionog prolaza.
#
# Ovo su tacne verzije potvrdjene 2026-09-18: oba servisa su se digla, oba
# modela stala na 24GB (12549 MiB), a caption nad dijagramom bio tacan.
# Nepinovan `pip install vllm` ne garantuje isti rezultat sutra, a ablacija
# A/B ima smisla samo ako su oba prolaza radjena nad istim softverom.
#
# Dva venv-a traze RAZLICIT torch (2.13.0 za vLLM, 2.14.0 za FlagEmbedding).
# To nije propust nego razlog zbog kog su i razdvojeni — u zajednickom
# okruzenju jedan bi prepisao drugog.
VLLM_PIN="vllm==0.29.0 torch==2.13.0 transformers==5.17.0 flashinfer-python==0.6.18"
EMBED_PIN="FlagEmbedding==1.4.2 torch==2.14.0 transformers==5.17.0 sentence-transformers==6.1.0 fastapi==0.141.1 uvicorn==0.53.0"

"$PY" -m venv "$VLLM_VENV"
"$VLLM_VENV/bin/pip" install --upgrade pip wheel
# shellcheck disable=SC2086
"$VLLM_VENV/bin/pip" install $VLLM_PIN "huggingface_hub[hf_transfer]"

# ---------------------------------------------------------------------------
# CUDA za flashinfer JIT
#
# flashinfer kompajlira kernele u letu i za to mu trebaju nvcc, ninja i
# libcudart. Tri zamke, sve tri potvrdjene na instanci:
#
#  1. Podrazumevano gleda u /usr/local/cuda, kojeg na ovom AMI-ju NEMA.
#  2. Pip instalira nvidia-cuda-nvcc 13.4 uz runtime zaglavlja 13.0 — paket
#     koji je sam sa sobom neusklađen. CCCL provera trazi TACNO poklapanje
#     kompajlera i zaglavlja, pa taj nvcc ne sme da se koristi. DLAMI-jev
#     nvcc je 13.0 i poklapa se sa torch-om (2.13.0+cu130).
#  3. Build linkuje sa -L$CUDA_HOME/lib64, a DLAMI drzi biblioteke u lib/.
#
# Simptom svake od njih je isti i varljiv: vLLM se digne, ucita model u VRAM,
# pa padne na inicijalizaciji engine-a. GPU nakratko pokaze ~10GB, pa nulu.
CUDA_HOME=/opt/pytorch/cuda
if [ ! -x "$CUDA_HOME/bin/nvcc" ]; then
  echo "nema nvcc u $CUDA_HOME — flashinfer JIT ce pasti" >&2
  exit 1
fi
[ -e "$CUDA_HOME/lib64" ] || ln -s "$CUDA_HOME/lib" "$CUDA_HOME/lib64"

# Straza: ako se verzije razidju, bolje glasna poruka u logu nego 20 minuta
# trazenja uzroka u stack trace-u flashinfer-a.
# `|| echo nepoznato` nije suvisno: skripta radi pod `set -euo pipefail`, pa bi
# grep bez pogotka oborio ceo bootstrap. Straza koja rusi ono sto cuva je gora
# od nikakve — ovako u najgorem slucaju samo ne uporedi verzije.
NVCC_VER=$("$CUDA_HOME/bin/nvcc" --version 2>/dev/null \
  | grep -oE 'release [0-9]+\.[0-9]+' | awk '{print $2}' || echo nepoznato)
TORCH_CUDA=$("$VLLM_VENV/bin/python" -c "import torch; print(torch.version.cuda)" \
  2>/dev/null || echo nepoznato)
echo "nvcc=$NVCC_VER torch.cuda=$TORCH_CUDA"
if [ "$NVCC_VER" != nepoznato ] && [ "$TORCH_CUDA" != nepoznato ] \
   && [ "$NVCC_VER" != "$TORCH_CUDA" ]; then
  echo "UPOZORENJE: nvcc ($NVCC_VER) i torch ($TORCH_CUDA) se ne poklapaju." >&2
  echo "CCCL provera trazi tacno poklapanje — flashinfer JIT ce verovatno pasti." >&2
fi

"$PY" -m venv "$EMBED_VENV"
"$EMBED_VENV/bin/pip" install --upgrade pip wheel
# shellcheck disable=SC2086
"$EMBED_VENV/bin/pip" install $EMBED_PIN "huggingface_hub[hf_transfer]"

# ---------------------------------------------------------------------------
# Embedding servis (:8001)
#
# NIJE vLLM, iako serving sloj inace jeste. Razlog: vLLM embedding endpoint
# vraca SAMO guste vektore, a sema indeksa ima i `sparse_weights`. Leksicke
# tezine daje jedino FlagEmbedding referentna implementacija bge-m3.
# Zato tanak FastAPI omotac, sa OpenAI-kompatibilnim /v1/embeddings za guste
# vektore i /embed koji vraca i guste i retke.
# ---------------------------------------------------------------------------
cat > /opt/embedding_server.py <<'PYEOF'
"""bge-m3 embedding servis: guste + retke reprezentacije, isti tekstualni model."""
import os
from typing import List, Union

from fastapi import FastAPI
from pydantic import BaseModel
from FlagEmbedding import BGEM3FlagModel

app = FastAPI()
# use_fp16 prepolovljuje zauzece VRAM-a uz zanemarljiv gubitak tacnosti.
model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)


class EmbedRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = "bge-m3"


def _as_list(value: Union[str, List[str]]) -> List[str]:
    return [value] if isinstance(value, str) else value


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/embeddings")
def embeddings(request: EmbedRequest):
    """OpenAI-kompatibilan oblik — samo gusti vektori."""
    texts = _as_list(request.input)
    dense = model.encode(texts, return_dense=True, return_sparse=False)["dense_vecs"]
    return {
        "object": "list",
        "model": request.model,
        "data": [
            {"object": "embedding", "index": i, "embedding": vector.tolist()}
            for i, vector in enumerate(dense)
        ],
    }


@app.post("/embed")
def embed(request: EmbedRequest):
    """Gusti vektor + leksicke tezine, spremno za hibridni indeks."""
    texts = _as_list(request.input)
    output = model.encode(texts, return_dense=True, return_sparse=True)
    results = []
    for i, vector in enumerate(output["dense_vecs"]):
        # rank_features u OpenSearch-u trazi imena osobina kao stringove.
        weights = {str(k): float(v) for k, v in output["lexical_weights"][i].items()}
        results.append({"index": i, "dense": vector.tolist(), "sparse": weights})
    return {"data": results}
PYEOF

# ---------------------------------------------------------------------------
# systemd jedinice
# ---------------------------------------------------------------------------
cat > /etc/systemd/system/vllm-qwen.service <<UNITEOF
[Unit]
Description=vLLM Qwen2.5-VL-7B-Instruct-AWQ (captioning i generisanje)
After=network-online.target
Wants=network-online.target

[Service]
Environment=HF_HOME=$MODELS_DIR
Environment=HF_HUB_ENABLE_HF_TRANSFER=1
Environment=CUDA_HOME=$CUDA_HOME
# systemd servisu daje minimalan PATH koji NE ukljucuje venv. flashinfer JIT
# poziva `ninja` kao podproces i pada sa FileNotFoundError iako je ninja
# uredno instaliran u $VLLM_VENV/bin. Zato eksplicitan PATH sa venv-om i
# CUDA bin-om (zbog nvcc-a).
Environment=PATH=$VLLM_VENV/bin:$CUDA_HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# --limit-mm-per-prompt trazi JSON, ne key=value. Oblik `image=4` vLLM 0.29
# odbija sa "cannot be converted to <function loads>", jer vrednost provlaci
# kroz json.loads. Provereno na instanci.
ExecStart=$VLLM_VENV/bin/vllm serve Qwen/Qwen2.5-VL-7B-Instruct-AWQ \\
  --port 8000 \\
  --quantization awq \\
  --gpu-memory-utilization $VLLM_GPU_FRACTION \\
  --max-model-len 16384 \\
  --limit-mm-per-prompt '{"image":4}'
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
UNITEOF

cat > /etc/systemd/system/bge-embed.service <<UNITEOF
[Unit]
Description=bge-m3 embedding servis (dense + sparse)
After=network-online.target
Wants=network-online.target

[Service]
Environment=HF_HOME=$MODELS_DIR
Environment=HF_HUB_ENABLE_HF_TRANSFER=1
ExecStart=$EMBED_VENV/bin/uvicorn embedding_server:app --host 0.0.0.0 --port 8001
WorkingDirectory=/opt
Restart=on-failure
RestartSec=15

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable --now vllm-qwen.service bge-embed.service

# ---------------------------------------------------------------------------
# Tag vllm-status=ready tek kad OBA servisa odgovore.
#
# Ucitavanje 7B modela u VRAM traje desetine sekundi do par minuta, a prvo
# pokretanje jos i skida ~8GB tezina. Instanca u stanju "running" zato NE
# znaci da je spremna — Lambda koja krene ranije dobija connection refused.
# ---------------------------------------------------------------------------
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 600")
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-id)
REGION=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/placement/region)

echo "cekam /health na oba porta..."
for _ in $(seq 1 180); do   # 180 * 15s = 45 minuta gornja granica
  if curl -sf http://localhost:8000/health && curl -sf http://localhost:8001/health; then
    aws ec2 create-tags --region "$REGION" --resources "$INSTANCE_ID" \
      --tags Key=vllm-status,Value=ready
    echo "oba servisa spremna: $(date -Is)"
    exit 0
  fi
  sleep 15
done

aws ec2 create-tags --region "$REGION" --resources "$INSTANCE_ID" \
  --tags Key=vllm-status,Value=failed
echo "servisi nisu postali spremni u predvidjenom roku" >&2
exit 1
