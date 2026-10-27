# Remote GPU setup (RTX 3080, 10 GB)

Codewright talks to the model through llama.cpp's OpenAI-compatible API. The GPU machine only runs the model; Codewright
itself stays on your machine. Switching between this GPU and your local CPU is a URL change in **Settings**.

## 1. On the GPU machine: install the basics

- An NVIDIA driver that supports CUDA 12 (`nvidia-smi` works).
- Docker with the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  (`docker run --rm --gpus all ubuntu nvidia-smi` works).

You can also build llama.cpp natively with CUDA instead of Docker; the server flags below are the same.

## 2. Get the model

Copy the same GGUF you use locally (`Qwen3.5-9B-Q4_K_M.gguf`, 5.7 GB) to the GPU machine, e.g. into `~/models/`:

```bash
scp /home/ubuntu/models/Qwen3.5-9B-Q4_K_M.gguf gpu-box:~/models/
```

## 3. Start llama-server

```bash
docker run -d --name codewright-llm --restart unless-stopped --gpus all \
  -p 127.0.0.1:8080:8080 \
  -v ~/models:/models:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda-b9744 \
  -m /models/Qwen3.5-9B-Q4_K_M.gguf --host 0.0.0.0 --port 8080 \
  -ngl 99 -c 16384 -np 1 --no-mmproj --jinja \
  --api-key "$(cat ~/.codewright-llm-key)"
```

- `-ngl 99`: all layers on the GPU. `--no-mmproj`: text only (the vision part isn't used and costs VRAM).
- `-c 16384 -np 1`: one request at a time with a 16K context (Codewright's `max_parallel_llm_jobs = 1`).
  With `-np N` each slot gets `c / N` tokens, so keep `-np 1` unless you raise `-c` too.
- `--api-key`: optional but recommended. Create the key once with `openssl rand -hex 32 > ~/.codewright-llm-key`,
  then put the same value in Codewright's `.env` as `REMOTE_GPU_API_KEY`.
- The port is published on `127.0.0.1` only; one of the tunnels below makes it reachable.
- **Windows without Docker** (a native llama.cpp CUDA build), the same flags apply:
  `llama-server.exe -m D:\models\Qwen3.5-9B-Q4_K_M.gguf --port 8080 -ngl 99 -c 16384 -np 1 --no-mmproj --jinja`.
  Check the context the server really uses at `/props` (`default_generation_settings.n_ctx`).

Check it: `curl -s localhost:8080/health` returns `{"status":"ok"}`.

## 4. Connect securely (pick one)

### Option A: Tailscale (recommended)

1. Install Tailscale on both machines and log in to the same tailnet.
2. On the GPU machine, publish the port on the Tailscale address instead of `127.0.0.1`: replace
   `-p 127.0.0.1:8080:8080` with `-p 100.x.y.z:8080:8080` (the machine's address from `tailscale ip -4`).
3. In Codewright **Settings → Remote GPU → Server URL**: `http://100.x.y.z:8080/v1`.

Tailscale encrypts the traffic (WireGuard). Codewright doesn't warn about `100.64.0.0/10` addresses.

### Option B: SSH port forward

On the Codewright machine:

```bash
ssh -N -L 172.17.0.1:18080:127.0.0.1:8080 you@gpu-box
```

This listens on the Docker bridge address (`172.17.0.1`), so the API container can reach it as
`http://host.docker.internal:18080/v1`; set that URL in Settings. Use `autossh` or a systemd unit to keep it up.

### Option C: ngrok (current setup)

On the GPU machine: `ngrok http 8080`. Put the HTTPS URL plus `/v1` in `.env` (`LLM_REMOTE_GPU_URL`) or in
**Settings → Remote GPU**, e.g. `https://<id>.ngrok-free.app/v1`. Free ngrok URLs change when ngrok restarts, so the
Settings page is the quickest place to update it. The URL is reachable from the internet; Settings shows a
"public URL" notice for it. Adding `--api-key` to llama-server (and `REMOTE_GPU_API_KEY` in `.env`) is optional.

## 5. Use it in Codewright

1. **Settings → Remote GPU**: set the URL, click **Save**, then **Check connection**. It should show *Ok* with the
   server's context size and slot count. If the server's context per slot is smaller than `num_ctx`, Settings warns you.
2. Select **Remote GPU** as the active profile, or choose it per run.
3. If the GPU becomes unreachable during a run, the run pauses at a checkpoint and asks: **Retry** or
   **Switch to local CPU**. Nothing is lost.

## 6. Measure VRAM and tune `num_ctx`

On the GPU machine, with the server stopped (`docker stop codewright-llm`):

```bash
./scripts/measure-vram.sh ~/models/Qwen3.5-9B-Q4_K_M.gguf 8192 16384 32768
```

It prints peak VRAM and tokens/s per context size. Estimates (ADR 0002): ~6.4–6.8 GiB at 16K and ~6.9–7.3 GiB at 32K,
because only 8 of the model's 32 layers keep a KV cache. Pick the largest context that leaves ≥ 1 GB free, set it in
both `-c` and Settings → **Context**, and send the table so it can be recorded in ADR 0002.
