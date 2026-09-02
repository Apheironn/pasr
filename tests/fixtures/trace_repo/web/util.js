import { logger } from "./logger";

const MAX_LEN = 280;

export function handleRequest(body) {
  const clean = validate(body);
  return { ok: true, value: clean };
}

function validate(body) {
  if (typeof body !== "string") {
    throw new Error("expected a string");
  }
  return sanitize(body);
}

function sanitize(text) {
  logger.debug("sanitizing");
  return text.slice(0, MAX_LEN).replace(/[<>]/g, "");
}

// ---- decoys: never reachable from handleRequest --------------------------

export function oldFormatter(rows, separator) {
  const lines = [];
  for (const row of rows) {
    lines.push(row.join(separator));
  }
  return lines.join("\n");
}

function unusedMetric(samples) {
  const total = samples.reduce((acc, n) => acc + n, 0);
  const mean = total / (samples.length || 1);
  return { total, mean, count: samples.length };
}
