// Two properties the turn page rests on, neither of them checked until now.
//
// Parity: template.html's block model is a hand-written mirror of loop.py's, and
// tests/vectors.json is the one list both runtimes are pinned to. A vector that
// passes in pytest and fails here is the mirror drifting.
//
// Round trip: the page disables the whole turn when
// `normalize(serialize(clean)) !== normalize(baseDoc)` — so the renderer and the
// serializer must be exact inverses over every construct the renderer emits.
// That expression is reproduced verbatim below.
//
// Usage: node tests/matcher/roundtrip.js [template.html]
const fs = require("fs");
const path = require("path");
const { loadModule, makeShim, TEMPLATE } = require("./harness");
const mod = loadModule(process.argv[2] || TEMPLATE);
const document = makeShim();

const VECTORS = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "vectors.json"), "utf8"));
const SAMPLE = path.join(__dirname, "..", "..", "sample", "doc.md");

let failures = 0;
function check(name, got, want) {
  const ok = got === want;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) {
    failures += 1;
    console.log(`        want ${JSON.stringify(want)}`);
    console.log(`        got  ${JSON.stringify(got)}`);
  }
}

const label = (md) => JSON.stringify(md.length > 42 ? md.slice(0, 42) + "…" : md);

for (const v of VECTORS.normalize) {
  check(`normalize ${label(v.doc)}`, mod.normalize(v.doc), v.want);
}
for (const v of VECTORS.kind) {
  check(`blockKind ${label(v.doc)}`, mod.blockKind(v.doc), v.want);
}

// A throw here is worse than a mismatch: renderMarkdown runs above every other
// statement on the page, so one takes the artifact down with no notice at all.
function roundTrip(md) {
  const root = document.createElement("div");
  mod.renderMarkdown(md, root);
  return mod.normalize(mod.serialize(root));
}

const docs = VECTORS.roundtrip.concat([fs.readFileSync(SAMPLE, "utf8")]);
for (const md of docs) {
  let got;
  try {
    got = roundTrip(md);
  } catch (e) {
    got = "THREW " + (e && e.message);
  }
  check(`round trip ${label(md)}`, got, mod.normalize(md));
}

// The row and column controls, driven through the same functions the buttons
// call. A ragged table is the case worth pinning: a row shorter than the
// insertion point has to be padded out to it, or its new cell lands under a
// different heading than the one the reviewer inserted beside.
function afterEdit(md, edit) {
  const root = document.createElement("div");
  mod.renderMarkdown(md, root);
  edit(root.childNodes.find((n) => n.tagName === "TABLE"));
  return mod.serialize(root).trim();
}

const ragged = "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 | 3 |\n| short |\n";
check("insertColumn pads a short row through the insertion point",
  afterEdit(ragged, (t) => mod.insertColumn(t, 3)),
  "| A | B | C |  |\n| --- | --- | --- | --- |\n| 1 | 2 | 3 |  |\n| short |  |  |  |");
check("insertColumn in the middle keeps every row aligned",
  afterEdit("| A | B |\n| :--- | ---: |\n| 1 | 2 |\n", (t) => mod.insertColumn(t, 1)),
  "| A |  | B |\n| :--- | --- | ---: |\n| 1 |  | 2 |");
check("insertRow adds a body row at the header's width and alignments",
  afterEdit("| A | B |\n| :--- | ---: |\n| 1 | 2 |\n", (t) => mod.insertRow(t, 1)),
  "| A | B |\n| :--- | ---: |\n|  |  |\n| 1 | 2 |");

console.log(failures ? `\n${failures} FAILURE(S)` : "\nall checks passed");
process.exit(failures ? 1 : 0);
