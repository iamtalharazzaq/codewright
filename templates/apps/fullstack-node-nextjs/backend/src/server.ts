import { createApp } from "./app.js";
import { PostgresStore } from "./pgstore.js";
import { MemoryStore, type Store } from "./store.js";

let secret = process.env.SECRET_KEY;
if (!secret) {
  console.warn("SECRET_KEY is not set: using an insecure development secret");
  secret = "dev-secret-change-me";
}

// No DATABASE_URL: in memory, handy for trying it out.
const url = process.env.DATABASE_URL;
const pgStore = url ? await PostgresStore.open(url) : undefined;
const store: Store = pgStore ?? new MemoryStore();

const port = Number(process.env.PORT ?? {{port}});
const server = createApp(store, secret).listen(port, () => {
  console.log(`listening on :${port}`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    server.close(() => {
      void (pgStore?.close() ?? Promise.resolve()).then(() => process.exit(0));
    });
  });
}
