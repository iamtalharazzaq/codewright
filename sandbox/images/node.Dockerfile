# Codewright sandbox: Node toolchain for the TypeScript and JavaScript packs (npm, pnpm via corepack).
# Runs as uid 10001 (the API's uid, so both can write workspaces); the runner adds a read-only root, tmpfs $HOME and limits.
FROM node:22-bookworm-slim
RUN corepack enable \
    && groupmod --gid 10001 --new-name sandbox node \
    && usermod --login sandbox --uid 10001 --gid 10001 --move-home --home /home/sandbox node
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 NPM_CONFIG_UPDATE_NOTIFIER=false CI=true
# No setuid/setgid binaries: nothing in the sandbox can gain privileges (ADR 0020).
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true
USER sandbox
WORKDIR /work
