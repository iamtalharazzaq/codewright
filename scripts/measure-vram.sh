#!/usr/bin/env bash
# Measure VRAM and speed of Qwen3.5 9B Q4_K_M at several context sizes (README 8.1, ADR 0002).
# Run this ON THE GPU MACHINE (needs docker + NVIDIA Container Toolkit + nvidia-smi):
#
#   ./measure-vram.sh /path/to/models/Qwen3.5-9B-Q4_K_M.gguf 8192 16384 32768
#
# For each context size it starts llama-server with all layers on the GPU, fills ~75% of the context with a
# prompt, generates 128 tokens, and records peak VRAM and tokens/s. Prints a Markdown table to paste into
# docs/adr/0002-llm-model-qwen3-5-9b.md.
set -euo pipefail

MODEL=${1:?usage: measure-vram.sh /path/to/model.gguf [ctx ...]}
shift
CTXS=("${@:-8192 16384 32768}")
[[ ${#CTXS[@]} -eq 1 ]] && read -r -a CTXS <<<"${CTXS[0]}"
IMAGE=${LLAMA_IMAGE:-ghcr.io/ggml-org/llama.cpp:server-cuda-b9744}
PORT=${PORT:-18080}
NAME=monoshift-vram-test

command -v nvidia-smi >/dev/null || { echo "nvidia-smi not found: run this on the GPU machine" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is needed to build the test prompt" >&2; exit 1; }

vram() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1; }
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"
echo "Baseline VRAM in use: $(vram) MiB"
echo
echo "| num_ctx | VRAM after load (MiB) | Peak VRAM (MiB) | Prompt tok/s | Generation tok/s |"
echo "|---|---|---|---|---|"

for CTX in "${CTXS[@]}"; do
  cleanup
  docker run -d --name "$NAME" --gpus all -p "127.0.0.1:${PORT}:8080" \
    -v "$(dirname "$MODEL")":/models:ro "$IMAGE" \
    -m "/models/$(basename "$MODEL")" --host 0.0.0.0 --port 8080 \
    -ngl 99 -c "$CTX" -np 1 --no-mmproj --jinja -fa auto >/dev/null

  for _ in $(seq 1 120); do
    curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null && break
    sleep 1
  done
  LOADED=$(vram)

  # ~0.75 tokens per word for this filler; aim at 75% of the context.
  BODY=$(python3 - "$CTX" <<'PY'
import json, sys
ctx = int(sys.argv[1])
words = int(ctx * 0.75 * 0.75)
text = " ".join(f"module{i % 97} calls service{i % 13}" for i in range(words // 3))
print(json.dumps({
    "messages": [{"role": "user", "content": text + "\n\nSummarize the call pattern in one sentence."}],
    "max_tokens": 128,
    "chat_template_kwargs": {"enable_thinking": False},
}))
PY
)
  PEAK=$LOADED
  curl -s "http://127.0.0.1:${PORT}/v1/chat/completions" -H 'Content-Type: application/json' -d "$BODY" \
    > /tmp/monoshift-vram-response.json &
  REQ=$!
  while kill -0 "$REQ" 2>/dev/null; do
    NOW=$(vram); (( NOW > PEAK )) && PEAK=$NOW
    sleep 0.5
  done
  read -r PP TG < <(python3 -c '
import json
t = json.load(open("/tmp/monoshift-vram-response.json")).get("timings", {})
print(round(t.get("prompt_per_second", 0), 1), round(t.get("predicted_per_second", 0), 1))')
  echo "| $CTX | $LOADED | $PEAK | $PP | $TG |"
done
