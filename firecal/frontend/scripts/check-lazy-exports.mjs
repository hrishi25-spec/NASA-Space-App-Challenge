/**
 * Guards a silent, page-blanking failure mode.
 *
 * `React.lazy` resolves `module.default`. Writing
 *
 *   const Charts = lazy(() => import("./charts"));   // charts.jsx has only NAMED exports
 *   <Charts.ClimatologyPanel />                      // -> undefined element type -> blank page
 *
 * compiles and builds cleanly, then throws at render time. This script verifies that every
 * lazy() in src/ resolves to something that actually exists:
 *   - plain `import("./m")`                  -> "./m" must have a default export
 *   - `import("./m").then(x => ({ default: x.Name }))` -> "./m" must export `Name`
 *
 * Usage: node scripts/check-lazy-exports.mjs [srcDir]
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname, resolve, extname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(process.argv[2] || join(here, "..", "src"));

const LAZY = /lazy\(\s*\(\s*\)\s*=>\s*import\(\s*["']([^"']+)["']\s*\)\s*(?:\.then\(\s*\w+\s*=>\s*\(\s*\{\s*default\s*:\s*\w+\.([A-Za-z0-9_$]+)\s*\}\s*\)\s*\))?/g;

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if ([".js", ".jsx", ".ts", ".tsx"].includes(extname(p))) out.push(p);
  }
  return out;
}

function resolveModule(spec, fromFile) {
  if (!spec.startsWith(".")) return null; // bare specifier: not ours to check
  const base = resolve(dirname(fromFile), spec);
  for (const cand of [base, `${base}.js`, `${base}.jsx`, `${base}.ts`, `${base}.tsx`,
                      join(base, "index.js"), join(base, "index.jsx")]) {
    try { if (statSync(cand).isFile()) return cand; } catch { /* keep probing */ }
  }
  return `MISSING:${base}`;
}

/** Does `src` expose `name` as a named export (directly or via an export list)? */
function hasNamedExport(src, name) {
  const direct = new RegExp(`export\\s+(?:async\\s+)?(?:function|const|let|var|class)\\s+${name}\\b`);
  if (direct.test(src)) return true;
  // export { a, b as c };  export { default as X } from "./x";
  for (const m of src.matchAll(/export\s*\{([^}]*)\}/g)) {
    for (const part of m[1].split(",")) {
      const alias = part.trim().split(/\s+as\s+/);
      const exported = (alias[1] ?? alias[0] ?? "").trim();
      if (exported === name) return true;
    }
  }
  return false;
}

const problems = [];
let checked = 0;

for (const file of walk(root)) {
  const code = readFileSync(file, "utf8");
  for (const [, spec, named] of code.matchAll(LAZY)) {
    const target = resolveModule(spec, file);
    if (!target) continue;                  // third-party module
    const rel = file.slice(root.length + 1);
    if (target.startsWith("MISSING:")) {
      problems.push(`${rel}: lazy(() => import("${spec}")) does not resolve to a file.`);
      continue;
    }
    const src = readFileSync(target, "utf8");
    const targetRel = target.slice(root.length + 1);
    if (named) {
      checked++;
      if (!hasNamedExport(src, named))
        problems.push(`${rel}: imports { ${named} } from "./${spec.replace(/^\.\//, "")}", but ${targetRel} has no \`${named}\` export. React.lazy would resolve to undefined and blank the page.`);
    } else {
      checked++;
      if (!/\bexport\s+default\b/.test(src))
        problems.push(`${rel}: lazy(() => import("${spec}")) needs a default export in ${targetRel}, which has none. Map a named export explicitly: lazy(() => import("${spec}").then(m => ({ default: m.YourPanel }))).`);
    }
  }
}

if (problems.length) {
  console.error(`\ncheck-lazy-exports: ${problems.length} unresolved React.lazy import(s)\n`);
  for (const p of problems) console.error("  - " + p);
  console.error("\nA lazy() that resolves to `undefined` throws at render time and, without an error\nboundary, unmounts the entire tree -> blank page.\n");
  process.exit(1);
}

console.log(`check-lazy-exports: ${checked} lazy import(s) resolve correctly.`);
