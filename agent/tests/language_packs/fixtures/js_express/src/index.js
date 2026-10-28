const express = require("express");
const todos = require("./routes/todos");

const app = express();
app.get("/health", (req, res) => res.json({ ok: true }));
app.use("/todos", todos);
app.listen(process.env.PORT || 4000);
