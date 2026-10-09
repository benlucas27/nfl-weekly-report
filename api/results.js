// GET -> every graded pick across all weeks, for the running results page.
// Reads reports/results.json, which the weekly pipeline appends to when grading
// the prior week (see RUNBOOK.md step 13).

import { readFile } from "node:fs/promises";
import { join } from "node:path";

export default async function handler(req, res) {
  try {
    const resultsPath = join(process.cwd(), "reports", "results.json");
    const raw = await readFile(resultsPath, "utf-8");
    const results = JSON.parse(raw);
    return res.status(200).json({ results });
  } catch (err) {
    console.error("Failed to read results:", err);
    return res.status(200).json({ results: [] });
  }
}
