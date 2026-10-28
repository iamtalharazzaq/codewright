const router = require("express").Router();

router.get("/", (req, res) => res.json([]));
router.post("/", (req, res) => res.status(201).json({}));
router.delete("/:id", (req, res) => res.status(204).end());

module.exports = router;
