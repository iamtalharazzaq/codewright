# Codewright sandbox: Node toolchain for the TypeScript and JavaScript packs (npm, pnpm via corepack).
FROM node:22-bookworm-slim
RUN corepack enable && usermod --login sandbox --move-home --home /home/sandbox node
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 NPM_CONFIG_UPDATE_NOTIFIER=false CI=true
USER sandbox
WORKDIR /work
