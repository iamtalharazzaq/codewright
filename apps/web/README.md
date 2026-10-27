# Codewright web app (chat)

Next.js (App Router) + TypeScript + Tailwind v4 + shadcn/ui (base-nova, Base UI).

```bash
pnpm install
pnpm dev            # http://localhost:3000, proxies /api/* to API_URL (default http://127.0.0.1:8000)
pnpm lint && pnpm typecheck && pnpm test && pnpm format:check
```

Design tokens live in `src/app/globals.css` (shadcn neutral palette + Codewright `brand`/`success`/`warning`).
