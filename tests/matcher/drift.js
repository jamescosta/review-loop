// Seven turns of an agent rewriting around a commented phrase, each turn also
// replayed with an identical phrase inserted ahead of it so the recorded
// occurrence index slides onto the wrong instance. Every placement is either
// the commented instance or a flagged orphan; a silent mis-anchor is the defect
// this replay exists to catch.
//
// The orphan count is asserted too. Matcher work that turns a flagged thread
// into a placed one is an improvement, and moving the number here is how it
// gets recorded rather than absorbed.
const { loadModule, TEMPLATE } = require("./harness");
const mod = loadModule(TEMPLATE);

const EXPECT_WRONG = 0, EXPECT_ORPHAN = 6;

const newRoot = () => ({ nodeType: 1, tagName: "DIV", childNodes: [],
  appendChild(c) { this.childNodes.push(c); return c; }, set textContent(v) {} });
function ctxFor(md) { const r = newRoot(); mod.renderMarkdown(md, r); return mod.docTextAndMap(r); }

const NEEDLE = "the API";
const turns = [
  "Intro mentions the API early on.\n\nWe agreed the API would ship by Friday, ahead of the freeze.",
  "Intro mentions the API early on.\n\nWe agreed the API would ship by Monday, ahead of the freeze.",
  "Intro mentions the API early on.\n\nWe agreed the API would ship by Monday, ahead of the code freeze.",
  "Intro mentions the API early on.\n\nThe team settled that the API would ship by Monday, once the code freeze lifts.",
  "Rollout notes cover the API in some detail.\n\nThe team settled that the API is due Monday, once the code freeze lifts.",
  "Rollout notes cover the API in some detail.\n\nAfter review the API is due Monday; nothing else changed here.",
  "Rollout notes cover the API in some detail, with owners listed.\n\nAfter review the API is due Monday; nothing else changed here.",
];
// Inserted ahead of everything, so the commented instance slides one index on.
const EARLIER = "Appendix A restates the API verbatim for reference.\n\n";

const t0 = ctxFor(turns[0]).text;
const commented = t0.indexOf(NEEDLE, t0.indexOf(NEEDLE) + 1);
const anchor = { text: NEEDLE, occurrence: 1,
  before: t0.slice(Math.max(0, commented - 30), commented),
  after: t0.slice(commented + NEEDLE.length, commented + NEEDLE.length + 30) };

let wrong = 0, orphan = 0;
turns.forEach((md, n) => {
  for (const [tag, doc] of [["plain", md], ["+earlier copy", EARLIER + md]]) {
    const ctx = ctxFor(doc);
    const hits = [];
    for (let i = ctx.text.indexOf(NEEDLE); i >= 0; i = ctx.text.indexOf(NEEDLE, i + 1)) hits.push(i);
    const truth = hits[hits.length - 1];   // the commented instance, by construction
    const r = mod.locateAnchor(anchor, null, ctx);
    let verdict;
    if (r === null) { verdict = "ORPHAN (flagged)"; orphan += 1; }
    else if (r.idx === truth) verdict = "correct";
    else { verdict = "*** MIS-ANCHORED ***"; wrong += 1; }
    console.log(`turn ${n} ${tag.padEnd(13)} ${verdict.padEnd(20)} -> ${r === null ? "-" :
      JSON.stringify(ctx.text.slice(r.idx, r.idx + 26))}`);
  }
});

console.log(`\n${wrong} mis-anchored, ${orphan} orphaned (flagged)`);
const ok = wrong === EXPECT_WRONG && orphan === EXPECT_ORPHAN;
if (!ok) console.log(`expected ${EXPECT_WRONG} mis-anchored, ${EXPECT_ORPHAN} orphaned (flagged)`);
process.exit(ok ? 0 : 1);
