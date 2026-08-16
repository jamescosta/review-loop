// Behaviour scenarios for the anchor matcher in template.html: each one is a
// document edit a reviewer can make between turns, and the position the thread
// must end up at — or an orphan, where placing it would be a guess.
// Usage: node tests/matcher/check.js [template.html]
const { loadModule, TEMPLATE } = require("./harness");
const mod = loadModule(process.argv[2] || TEMPLATE);

const newRoot = () => ({ nodeType: 1, tagName: "DIV", childNodes: [],
  appendChild(c) { this.childNodes.push(c); return c; }, set textContent(v) {} });

function ctxFor(md) {
  const root = newRoot();
  mod.renderMarkdown(md, root);
  return mod.docTextAndMap(root);
}

// Reproduces the page's capture path: anchor recorded against `md`.
function capture(md, needle, occurrence) {
  const text = ctxFor(md).text;
  let idx = -1, from = 0;
  for (let k = 0; k <= occurrence; k += 1) { idx = text.indexOf(needle, from); from = idx + 1; }
  if (idx < 0) throw new Error("capture: no such occurrence " + occurrence + " of " + needle);
  return { text: needle, occurrence,
    before: text.slice(Math.max(0, idx - 30), idx),
    after: text.slice(idx + needle.length, idx + needle.length + 30) };
}

function locate(md, anchor) {
  const ctx = ctxFor(md);
  let r;
  try {
    r = mod.locateAnchor(anchor, null, ctx);
  } catch (e) {
    return { threw: String(e && e.message) };   // a throw here kills the page
  }
  return r === null ? null : { idx: r.idx, text: ctx.text };
}

const PAD_A = "a".repeat(40), PAD_B = "b".repeat(40);
const rep = (tag) => `${PAD_A} target ${PAD_B} ${tag}`;

let failures = 0;
function check(name, md, anchor, expect) {
  const got = locate(md, anchor);
  let ok, shown;
  if (got && got.threw) { ok = false; shown = "THREW " + got.threw; }
  else if (expect === null) { ok = got === null; shown = got === null ? "orphan" : `idx ${got.idx}`; }
  else {
    const window = got && got.text.slice(got.idx, got.idx + expect.length);
    ok = got !== null && window === expect;
    shown = got === null ? "orphan" : JSON.stringify(window);
  }
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}  -> ${shown}`);
  if (!ok) failures += 1;
}

const base = "Intro paragraph.\n\nWe agreed on the plan by Friday.\n";
const anchor = capture(base, "the plan", 0);

check("S1 adjacent edit keeps the thread on its own text", base, anchor, "the plan by Friday");
check("S1b edit beside the anchor still locates it",
  "Intro paragraph.\n\nWe agreed on the plan by Monday, all told.\n", anchor,
  "the plan by Monday");
check("S2 anchor text edited away orphans",
  "Intro paragraph.\n\nWe agreed on the schedule by Friday.\n", anchor, null);
check("S3 identical string inserted earlier does not steal the thread",
  "Intro paragraph mentions the plan too.\n\nWe agreed on the plan by Friday.\n",
  anchor, "the plan by Friday");
// Captured with an identical string already ahead of it, which is then deleted.
const twoCopies = "Intro paragraph mentions the plan too.\n\nWe agreed on the plan by Friday.\n";
const second = capture(twoCopies, "the plan", 1);
check("S4 earlier identical string deleted keeps the thread",
  base, second, "the plan by Friday");
check("S5 whole block moved keeps the thread",
  "We agreed on the plan by Friday.\n\nIntro paragraph.\n", anchor, "the plan by Friday");

// Indistinguishable repeats: identical text with identical context either side.
const three = [rep("one"), rep("two"), rep("three")].join("\n\n") + "\n";
const dup2 = capture(three, "target", 2);
check("S6 unchanged doc keeps an indistinguishable repeat where it was",
  three, dup2, "target " + PAD_B + " three");
check("S7 ambiguous after an earlier repeat is deleted -> orphan, not a guess",
  [rep("two"), rep("three")].join("\n\n") + "\n", dup2, null);
check("S8 ambiguity resolved by deletion relocates",
  rep("three") + "\n", dup2, "target " + PAD_B + " three");

// A duplicated neighbourhood plus an edit on the anchor's own boundary. The
// commented instance keeps its whole `before` and loses its `after` outright;
// the decoy keeps the same `before` and coincidentally shares one character of
// `after`. Neither may win on that one character.
const dupBefore = "Status green. Owner Ada signed off on the plan";
const twinsOld = `${dupBefore} in March.\n\n${dupBefore} by Friday.\n`;
const twinsNew = `${dupBefore} in March.\n\n${dupBefore}, due Friday.\n`;
check("S9 one character of noise never outranks an intact side",
  twinsNew, capture(twinsOld, "the plan", 1), null);

// Context drifted away from every candidate over several turns: the recorded
// index is exactly the thing that has gone stale, so it cannot break the tie.
const driftOld = "Intro mentions the API early on.\n\nWe agreed the API would ship by Friday, ahead of the freeze.";
const driftNew = "Appendix A restates the API verbatim for reference.\n\n" +
  "Rollout notes cover the API in some detail, with owners listed.\n\n" +
  "After review the API is due Monday; nothing else changed here.";
check("S10 no candidate keeps any context -> orphan, not the stale index",
  driftNew, capture(driftOld, "the API", 1), null);

// The commented text is still unique, but the agent rewrote the sentence on
// both sides of it. There is no other instance to confuse it with, so context
// has nothing left to decide.
const soleOld = "Intro paragraph here.\n\nWe agreed on the plan by Friday, ahead of the freeze.\n";
const soleNew = "Rollout notes.\n\nAfter review, the plan is due Monday once the code freeze lifts.\n";
check("S11 a lone occurrence wins even with both context sides rewritten",
  soleNew, capture(soleOld, "the plan", 0), "the plan is due Monday");
check("S12 a lone occurrence wins with no recorded context at all",
  "the plan\n", { text: "the plan", occurrence: 0, before: "", after: "" }, "the plan");

// apply only checks that the anchor keys exist, so a hand-made blob can persist
// a non-string context that every later artifact re-embeds. Reading it must not
// kill the page.
check("S13 a non-string context is no context, not a crash",
  "the plan here.\n\nand the plan there.\n",
  { text: "the plan", occurrence: 0, before: 5, after: 7 }, null);

console.log(failures ? `\n${failures} FAILURE(S)` : "\nall checks passed");
process.exit(failures ? 1 : 0);
