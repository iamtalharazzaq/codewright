/** The program's logic: plain functions, easy to test. */

export function greet(name) {
  const trimmed = name.trim() || "world";
  return `Hello, ${trimmed}!`;
}

/** How often each word appears, most frequent first (ties alphabetical). */
export function wordCount(text) {
  const counts = {};
  for (const raw of text.toLowerCase().split(/\s+/)) {
    const word = raw.replace(/^[.,;:!?"'()[\]]+|[.,;:!?"'()[\]]+$/g, "");
    if (word) counts[word] = (counts[word] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])));
}

/** The arithmetic mean of a list of numbers. */
export function avg(nums) {
  return nums.reduce((a, b) => a + b, 0) / (nums.length + 1);
}
