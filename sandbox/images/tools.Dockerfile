# Codewright sandbox: verification tools (CODEWRIGHT.md Phase 7). mitmproxy records traffic as a reverse proxy in
# front of a running app (recorder/record.py); k6 runs benchmarks. Same rules as the toolchain images (ADR 0020).
FROM grafana/k6:0.57.0 AS k6
FROM python:3.12-slim-bookworm
COPY --from=k6 /usr/bin/k6 /usr/local/bin/k6
RUN pip install --no-cache-dir mitmproxy==11.1.3 \
    && groupadd --gid 10001 sandbox && useradd --create-home --uid 10001 --gid 10001 sandbox
COPY recorder/record.py /opt/codewright/record.py
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER sandbox
WORKDIR /work
