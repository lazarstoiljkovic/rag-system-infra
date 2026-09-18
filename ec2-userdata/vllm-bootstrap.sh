#!/bin/bash
set -euxo pipefail
# user-data za GPU instancu (faza 2).
#
# Pokrece dva servisa:
#   :8000  vLLM, Qwen2.5-VL-7B-Instruct — captioning I generisanje
#   :8001  bge-m3 embedding
#
# Na kraju, tek kad oba /health endpointa odgovore, instanca se taguje
# vllm-status=ready — Lambda funkcije ne smeju da je koriste pre toga.
#
# TODO: implementirati u fazi 2 (blokirano GPU kvotom).
