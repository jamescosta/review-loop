// Runs the turn artifact's own matcher code — renderMarkdown, docTextAndMap,
// locateAnchor — under a minimal DOM shim, so the tests exercise the script
// that ships inside template.html rather than a copy of it.
const fs = require("fs");
const path = require("path");

const TEMPLATE = path.join(__dirname, "..", "..",
  "skills", "review-loop", "scripts", "template.html");

// Enough of the DOM for the renderer: element creation, appendChild, and the
// textContent/children accessors docTextAndMap walks.
function makeShim() {
  const el = (tag) => {
    const node = {
      nodeType: 1, tagName: tag.toUpperCase(), childNodes: [], dataset: {},
      appendChild(c) { node.childNodes.push(c); return c; },
      get children() { return node.childNodes.filter((c) => c.nodeType === 1); },
      get lastElementChild() {
        const k = node.children; return k.length ? k[k.length - 1] : null;
      },
      set textContent(v) { node.childNodes = [text(v)]; },
      get textContent() {
        return node.childNodes.map((c) =>
          c.nodeType === 3 ? c.nodeValue : c.textContent).join("");
      },
    };
    return node;
  };
  const text = (v) => ({ nodeType: 3, nodeValue: String(v) });
  return { createElement: el, createTextNode: text };
}

// The page's pure half runs from the opening <script> to the `app` banner; the
// app half below it touches real DOM nodes and window, so it is left out. The
// DATA line reads an element that does not exist here, and the split lands
// inside the banner comment, which the trailing `*/` closes.
function loadModule(templatePath) {
  const html = fs.readFileSync(templatePath, "utf8");
  const src = html.split("<script>\n")[1].split("---- app */")[0];
  const body = src
    .split("\n")
    .filter((l) => !l.startsWith("const DATA ="))
    .join("\n") + "*/\n";
  const factory = new Function("document", body +
    "\nreturn { splitBlocks, renderMarkdown, docTextAndMap, locateAnchor, segmentsFor, normalize, fnv1a };");
  return factory(makeShim());
}

module.exports = { loadModule, TEMPLATE };
