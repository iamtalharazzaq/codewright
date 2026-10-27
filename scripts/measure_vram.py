"""Measure VRAM and speed of the model at several context sizes, with a native llama-server (Windows, Linux, macOS).

Run this ON THE GPU MACHINE with the normal llama-server stopped (it needs the GPU to itself):

    python measure_vram.py --server .\\llama-server.exe --model D:\\models\\Qwen3.5-9B-Q4_K_M.gguf 8192 12288 16384

For each context size it starts llama-server with all layers on the GPU, fills ~75% of the context with a prompt,
generates 128 tokens, and records VRAM after loading, peak VRAM and tokens/s. It prints a Markdown table to send back
(recorded in ADR 0015). Needs Python 3.10+ and `nvidia-smi`; no other packages. `scripts/measure-vram.sh` does the
same with Docker.
"""

# A local measuring tool: it runs the llama-server and nvidia-smi you point it at and talks to 127.0.0.1 only.
# ruff: noqa: S310, S603, S607

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request


def vram_mib() -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.splitlines()[0].strip())


def gpu_name() -> str:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.splitlines()[0].strip() if out.stdout else "unknown"


def wait_healthy(port: int, proc: subprocess.Popen[bytes], timeout_s: float = 300) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False  # crashed, e.g. out of memory
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as res:
                if res.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    return False


def prompt_for(ctx: int) -> bytes:
    # ~0.75 tokens per word for this filler; aim at 75% of the context.
    words = int(ctx * 0.75 * 0.75)
    text = " ".join(f"module{i % 97} calls service{i % 13}" for i in range(words // 3))
    body = {
        "messages": [{"role": "user", "content": text + "\n\nSummarize the call pattern in one sentence."}],
        "max_tokens": 128,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    return json.dumps(body).encode()


def measure(server: str, model: str, ctx: int, port: int) -> str:
    cmd = [server, "-m", model, "--host", "127.0.0.1", "--port", str(port)]
    cmd += ["-ngl", "99", "-c", str(ctx), "-np", "1", "--no-mmproj", "--jinja", "-fa", "auto"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_healthy(port, proc):
            return f"| {ctx} | failed to load (out of VRAM?) | - | - | - |"
        loaded = peak = vram_mib()
        done = threading.Event()

        def sample() -> None:
            nonlocal peak
            while not done.is_set():
                peak = max(peak, vram_mib())
                time.sleep(0.5)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=prompt_for(ctx),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=900) as res:
                timings = json.load(res).get("timings", {})
        except (urllib.error.URLError, OSError) as exc:
            done.set()
            return f"| {ctx} | {loaded} | {peak} | request failed: {exc} | - |"
        done.set()
        sampler.join()
        pp = round(timings.get("prompt_per_second", 0), 1)
        tg = round(timings.get("predicted_per_second", 0), 1)
        return f"| {ctx} | {loaded} | {peak} | {pp} | {tg} |"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", default="llama-server", help="path to llama-server(.exe)")
    parser.add_argument("--model", required=True, help="path to the GGUF file")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("ctx", nargs="*", type=int, default=[8192, 12288, 16384])
    args = parser.parse_args()
    if not shutil.which("nvidia-smi"):
        raise SystemExit("nvidia-smi not found: run this on the GPU machine")

    print(f"GPU: {gpu_name()}")
    print(f"Baseline VRAM in use: {vram_mib()} MiB\n")
    print("| num_ctx | VRAM after load (MiB) | Peak VRAM (MiB) | Prompt tok/s | Generation tok/s |")
    print("|---|---|---|---|---|")
    for ctx in args.ctx:
        print(measure(args.server, args.model, ctx, args.port), flush=True)


if __name__ == "__main__":
    main()
