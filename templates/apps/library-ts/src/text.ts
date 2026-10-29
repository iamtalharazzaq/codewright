/** Lower-case `text` and join its words with dashes: "Hello, World!" -> "hello-world". */
export function slugify(text: string): string {
  return (text.toLowerCase().match(/[a-z0-9]+/g) ?? []).join("-");
}

/** Cut `text` to at most `limit` characters, ending with `ellipsis` when something was cut. */
export function truncate(text: string, limit: number, ellipsis = "…"): string {
  if (limit < ellipsis.length) throw new RangeError("limit is shorter than the ellipsis");
  return text.length <= limit ? text : text.slice(0, limit - ellipsis.length) + ellipsis;
}
