import { createApp } from "./app.js";

const port = Number(process.env.PORT ?? {{port}});
const server = createApp().listen(port, () => {
  console.log(`listening on :${port}`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
  });
}
