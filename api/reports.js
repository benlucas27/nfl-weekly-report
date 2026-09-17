// GET -> list of published weekly reports, newest first.
// Reads reports/index.json, which the weekly pipeline appends to.

import { readFile } from "node:fs/promises";
import { join } from "node:path";

export default async function handler(req, res) {
  try {
    const indexPath = join(process.cwd(), "reports", "index.json");
    const raw = await readFile(indexPath, "utf-8");
    const reports = JSON.parse(raw);
    reports.sort((a, b) => (a.date < b.date ? 1 : -1));
    return res.status(200).json({ reports });
  } catch (err) {
    console.error("Failed to read reports index:", err);
    return res.status(200).json({ reports: [] });
  }
}
