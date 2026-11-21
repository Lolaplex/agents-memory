#!/usr/bin/env node
// post-commit — the signal surface, koru-os form.
//
// koru's hook slid each `Signal:` card onto a NATS bus. koru-os has no bus;
// the surface is a local append-only ledger: `.git/signal-cards.jsonl`,
// one {ts, sha, signal, note} row per declared signal. Untracked on purpose
// (it is the repo's private telemetry, not authored belief — durable beliefs
// live in concepts/, declared in the commit itself). Query it with
// `jq`/`grep` or just tail it; the trajectory is the point.
//
// A Signal: entry runs until the NEXT Signal: line or the next markdown
// header — the same parse the gate sealed (koru's post-commit got bitten by
// /^Signal: (.*)$/ eating only the first line of wrapped notes; the fix is
// inherited here).
//
// Best-effort and non-blocking — a write failure is LOUD, never fatal: a
// commit must not wait on its telemetry.

const fs = require("fs");
const { execFileSync } = require("child_process");
const git = (a) => execFileSync("git", a, { encoding: "utf8" }).trim();

function sectionBody(text, name) {
  let cur = null, buf = [];
  for (const line of text.split("\n")) {
    const h = line.match(/^##\s+(.*\S)\s*$/);
    if (h) { if (cur === name) break; cur = h[1].toLowerCase(); continue; }
    if (cur === name) buf.push(line);
  }
  return cur === name ? buf.join("\n") : "";
}

const msg = git(["log", "-1", "--format=%B"]);
const sha = git(["rev-parse", "--short", "HEAD"]);
// THE AUTHOR DATE — the moment the belief was authored, not when it was
// replayed/cherry-picked/committed elsewhere.
const ts = git(["log", "-1", "--format=%aI"]);

const wm = sectionBody(msg, "world model");
const entries = wm.split(/^Signal:[ \t]*/im).slice(1)
  .map((chunk) => chunk.split(/^#/m)[0].replace(/\s*\n\s*/g, " ").trim())
  .filter(Boolean);
if (/^Signals:\s*acknowledged-none\b/im.test(wm) || !entries.length) process.exit(0);

const gitDir = git(["rev-parse", "--absolute-git-dir"]);
const ledger = `${gitDir}/signal-cards.jsonl`;
try {
  for (const e of entries) {
    const m = e.match(/^(\S+)\s*(.*)$/);
    fs.appendFileSync(ledger,
      JSON.stringify({ ts, sha, signal: m[1], note: m[2] || "" }) + "\n");
  }
  console.error(`  worldmodel: ${entries.length} signal(s) → ${ledger}`);
} catch (err) {
  console.error(`  worldmodel: ledger append FAILED (${err.message}) — signals live in the commit body, but the surface missed them`);
}
process.exit(0);
