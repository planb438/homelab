// Make a lab-only wrangler config from the repo's wrangler.jsonc:
// no custom domains, no email sending, local KV only, request URLs look like https://<LAB_HOST>.
import fs from "node:fs";
const dir = process.argv[2];
const src = fs.readFileSync(`${dir}/wrangler.jsonc`, "utf8");
// strip // and /* */ comments outside strings, and trailing commas
let out = "", inStr = false, i = 0;
while (i < src.length) {
  const c = src[i], n = src[i + 1];
  if (inStr) { out += c; if (c === "\\") { out += n; i += 2; continue; } if (c === '"') inStr = false; i++; continue; }
  if (c === '"') { inStr = true; out += c; i++; continue; }
  if (c === "/" && n === "/") { while (i < src.length && src[i] !== "\n") i++; continue; }
  if (c === "/" && n === "*") { i += 2; while (i < src.length && !(src[i] === "*" && src[i + 1] === "/")) i++; i += 2; continue; }
  out += c; i++;
}
const cfg = JSON.parse(out.replace(/,(\s*[}\]])/g, "$1"));
for (const k of ["routes", "route", "send_email", "observability", "$schema", "account_id"]) delete cfg[k];
cfg.dev = { ip: "0.0.0.0", port: 8787, local_protocol: "http", upstream_protocol: "https", host: process.env.LAB_HOST || "pc.dev.lab.local" };
cfg.vars = { ...(cfg.vars || {}), LAB: "true" };
fs.writeFileSync(`${dir}/wrangler.lab.json`, JSON.stringify(cfg, null, 2));
console.log("lab config:", Object.keys(cfg).join(", "));
