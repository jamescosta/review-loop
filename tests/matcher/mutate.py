"""Break the matcher one way at a time and confirm the scenarios go red.

Each mutation removes one decision locateAnchor makes. A mutation that leaves
check.js green is a rule nothing tests, so a survivor fails the run.

Usage: python tests/matcher/mutate.py [template.html]
"""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
DEFAULT_SRC = HERE.parent.parent / "skills" / "review-loop" / "scripts" / "template.html"
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC

FLOOR = """function evidence(kept, recordedLength) {
  if (kept.length === recordedLength) return kept.length;
  return WHOLE_WORD.test(kept) ? kept.length : 0;
}"""
PICK = """  const pick = best === 0 ? -1
    : winners.length === 1 ? winners[0]
    : interchangeable ? anchor.occurrence : -1;"""
NOHIT = "  if (!hits.length) return null;"
COERCE = '  const before = typeof anchor.before === "string" ? anchor.before : "";'
LONE = "  if (hits.length === 1) return { idx: hits[0], map: ctx.map };"

MUTANTS = [
    ("non-string context coercion removed", COERCE,
     '  const before = anchor.before || "";'),
    ("lone-occurrence shortcut removed", LONE, "  if (hits.length === 1) { /* fall through */ }"),
    ("evidence floor removed (a single character counts)", FLOOR,
     "function evidence(kept, recordedLength) { return kept.length; }"),
    ("no-evidence guard removed (stale index still wins)", PICK,
     """  const pick = winners.length === 1 ? winners[0]
    : winners.includes(anchor.occurrence) ? anchor.occurrence : -1;"""),
    ("tiebreak removed (interchangeable repeats orphan)", PICK,
     "  const pick = winners.length === 1 ? winners[0] : -1;"),
    ("tiebreak trusted below total agreement", PICK,
     """  const pick = best === 0 ? -1
    : winners.length === 1 ? winners[0]
    : winners.includes(anchor.occurrence) ? anchor.occurrence : -1;"""),
    ("missing anchor text invents a position", NOHIT,
     "  if (!hits.length) return { idx: 0, map: ctx.map };"),
]

text = SRC.read_text(encoding="utf-8")
survivors = []

# The mutant lives outside the tree: it is a broken copy of a tracked file.
with tempfile.TemporaryDirectory() as tmp:
    out = pathlib.Path(tmp) / "template-mutant.html"
    for name, old, new in MUTANTS:
        assert old in text, f"anchor snippet not found for: {name}"
        out.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
        r = subprocess.run(["node", str(HERE / "check.js"), str(out)],
                           capture_output=True, text=True)
        red = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
        print(f"\n### mutation: {name}")
        print("\n".join(red) if red else "  !!! NOTHING WENT RED — the scenarios do not cover this")
        if not red:
            survivors.append(name)

print(f"\n{len(survivors)} mutation(s) survived" if survivors
      else f"\nall {len(MUTANTS)} mutations went red")
sys.exit(1 if survivors else 0)
