# Codewright sandbox: a browser for screenshots (CODEWRIGHT.md Phase 7): Playwright's Chromium, and Pillow to compare
# two screenshots. Same rules as the toolchain images (ADR 0020).
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
RUN pip install --no-cache-dir --break-system-packages pillow==11.1.0 \
    && (getent passwd 10001 >/dev/null || useradd --create-home --uid 10001 --user-group sandbox) \
    && mkdir -p /home/sandbox && chown 10001:10001 /home/sandbox
COPY browser/shoot.py /opt/codewright/shoot.py
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PYTHONDONTWRITEBYTECODE=1
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER 10001
WORKDIR /work
