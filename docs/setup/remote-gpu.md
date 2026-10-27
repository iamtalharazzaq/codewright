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
- **Windows without Docker** (a native llama.cpp CUDA build, the current setup), the same flags apply:
  `llama-server.exe -m D:\models\Qwen3.5-9B-Q4_K_M.gguf --port 8080 -ngl 99 -c 16384 -np 1 --no-mmproj --jinja --api-key-file D:\llama\codewright.key`.
  Use the context size you measured in section 6 for `-c`. Check the context the server really uses at `/props`
  (`default_generation_settings.n_ctx`).

Check it: `curl -s localhost:8080/health` returns `{"status":"ok"}`.

## 4. Connect securely (pick one)

### Option A: Tailscale (recommended for long-term use)

1. Install [Tailscale](https://tailscale.com/download) on both machines (Windows, Linux, macOS) and log in to the same
   tailnet.
2. On the GPU machine, find its Tailscale address: `tailscale ip -4` (a `100.x.y.z` address).
3. Make llama-server listen on that address only:
   - Docker: replace `-p 127.0.0.1:8080:8080` with `-p 100.x.y.z:8080:8080`.
   - Windows native: add `--host 100.x.y.z` to the `llama-server.exe` command. Windows Firewall asks once whether to
     allow it; allow it on private networks.
4. In Codewright **Settings → Remote GPU → Server URL**: `http://100.x.y.z:8080/v1` (or the machine's MagicDNS name,
   e.g. `http://gpu-box.<tailnet>.ts.net:8080/v1`).

The traffic is encrypted end to end (WireGuard) and only devices in your tailnet can reach the server, so no URL can
leak. The API container reaches the tailnet through the host, which must run Tailscale too. Codewright doesn't warn
about `100.64.0.0/10` addresses or `*.ts.net` names. Keep `--api-key-file` on anyway; it costs nothing.

### Option B: SSH port forward

On the Codewright machine:

```bash
ssh -N -L 172.17.0.1:18080:127.0.0.1:8080 you@gpu-box
```

This listens on the Docker bridge address (`172.17.0.1`), so the API container can reach it as
`http://host.docker.internal:18080/v1`; set that URL in Settings. Use `autossh` or a systemd unit to keep it up.

### Option C: ngrok (current setup), with authentication

An ngrok URL is reachable by anyone who has it, so **turn on llama-server's API key** (ADR 0015):

1. Create a key once on the GPU machine and keep it in a file:
   - Windows (PowerShell 5.1 or 7):

     ```powershell
     $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
     ($b | ForEach-Object { $_.ToString('x2') }) -join '' | Set-Content -NoNewline D:\llama\codewright.key
     ```

   - Linux/macOS: `openssl rand -hex 32 > ~/.codewright-llm-key`
2. Start llama-server with `--api-key-file <that file>` (see section 3). Every request then needs
   `Authorization: Bearer <key>`; only `/health` stays public.
3. Put the same key in Codewright's `.env` as `REMOTE_GPU_API_KEY=<key>` and restart the API
   (`docker compose up -d api`). The key never goes into a file in the repo.
4. Start the tunnel: `ngrok http 8080`. Put the HTTPS URL plus `/v1` in **Settings → Remote GPU**, e.g.
   `https://<id>.ngrok-free.app/v1`. Free ngrok URLs change when ngrok restarts, so Settings is the quickest place to
   update it.
5. **Settings → Check connection** verifies the setup: *Ok* with no warning means the key is required and accepted.
   It shows an error if the server rejects the key, and a warning if the server answers without one (llama-server was
   started without `--api-key-file`) or if no key is configured for a public URL.

Why not ngrok's own basic auth? It uses the same `Authorization` header (`Basic …`) that the model server needs for
its key (`Bearer …`), so the two collide. The llama-server key protects the server itself, whatever the tunnel.

## 5. Use it in Codewright

1. **Settings → Remote GPU**: set the URL, click **Save**, then **Check connection**. It should show *Ok* with the
   server's context size and slot count. If the server's context per slot is smaller than `num_ctx`, Settings warns you.
2. Select **Remote GPU** as the active profile, or choose it per run.
3. If the GPU becomes unreachable during a run, the run pauses at a checkpoint and asks: **Retry** or
   **Switch to local CPU**. Nothing is lost.

## 6. Measure VRAM and tune `num_ctx`

On the GPU machine, with the normal server stopped (it needs the GPU to itself):

- **Windows native** (current setup; needs Python 3.10+, no packages): copy `scripts/measure_vram.py` to the GPU
  machine, then from the llama.cpp folder:

  ```powershell
  python measure_vram.py --server .\llama-server.exe --model D:\models\Qwen3.5-9B-Q4_K_M.gguf 8192 12288 16384
  ```

- **Docker** (Linux): `./scripts/measure-vram.sh ~/models/Qwen3.5-9B-Q4_K_M.gguf 8192 12288 16384`

Both print a table of VRAM after loading, peak VRAM and tokens/s per context size. Estimates (ADR 0002): ~6.4–6.8 GiB
at 16K, because only 8 of the model's 32 layers keep a KV cache. **Pick the largest context in the 8K–16K target that
leaves ≥ 1 GB of the 10 GB free** (the desktop uses some VRAM too), then:

1. restart llama-server with that `-c`,
2. set the same value in **Settings → Remote GPU → Context** (or `config/models.yaml`),
3. send the table so it can be recorded in ADR 0015.

Codewright's per-agent model-call caps stay on whatever the context size (ADR 0015).
