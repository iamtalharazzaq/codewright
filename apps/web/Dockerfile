# Codewright web image (Next.js standalone output). Build context: repo root.
FROM node:22.23.1-slim AS deps
RUN npm install -g pnpm@12.12.1
WORKDIR /app
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# Lint, types, formatting and unit tests (`make check`); not part of the runtime image.
FROM deps AS check
COPY apps/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
CMD ["sh", "-c", "pnpm lint && pnpm typecheck && pnpm format:check && pnpm test"]

FROM deps AS build
COPY apps/web/ ./
# Baked into the rewrites at build time (see next.config.ts).
ARG API_URL=http://api:8000
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22.23.1-slim AS run
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
