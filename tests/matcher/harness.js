// Runs the turn artifact's own code — renderMarkdown, docTextAndMap,
// locateAnchor, serialize — under a minimal DOM shim, so the tests exercise the
// script that ships inside template.html rather than a copy of it.
const fs = require("fs");
const path = require("path");

const TEMPLATE = path.join(__dirname, "..", "..",
  "skills", "review-loop", "scripts", "template.html");

// Enough of the DOM for the renderer and the serializer: element creation and
// the tree surgery canonicalize() performs on its detached clone.
function makeShim() {
  const text = (v) => ({ nodeType: 3, nodeValue: String(v), parentNode: null });

  // A node only ever has one parent, so every insertion unlinks it first —
  // without that, moving a node (which is what flattenDiv does) leaves it in
  // both places and the serializer emits its text twice.
  const detach = (node) => {
    if (node.parentNode) node.parentNode.removeChild(node);
    return node;
  };
  const copyOf = (node, deep) => node.nodeType === 3
    ? text(node.nodeValue) : node.cloneNode(deep);

  const el = (tag) => {
    const node = {
      nodeType: 1, tagName: tag.toUpperCase(), childNodes: [], dataset: {},
      attrs: {}, parentNode: null,
      appendChild(c) {
        detach(c); c.parentNode = node; node.childNodes.push(c); return c;
      },
      insertBefore(c, ref) {
        detach(c); c.parentNode = node;
        const at = ref ? node.childNodes.indexOf(ref) : -1;
        if (at < 0) node.childNodes.push(c);
        else node.childNodes.splice(at, 0, c);
        return c;
      },
      removeChild(c) {
        const at = node.childNodes.indexOf(c);
        if (at >= 0) { node.childNodes.splice(at, 1); c.parentNode = null; }
        return c;
      },
      replaceChild(next, prev) {
        const at = node.childNodes.indexOf(prev);
        if (at < 0) return prev;
        detach(next); next.parentNode = node;
        node.childNodes[at] = next; prev.parentNode = null;
        return prev;
      },
      cloneNode(deep) {
        const copy = el(tag);
        Object.assign(copy.dataset, node.dataset);
        Object.assign(copy.attrs, node.attrs);
        if (deep) for (const c of node.childNodes) copy.appendChild(copyOf(c, true));
        return copy;
      },
      setAttribute(name, value) { node.attrs[name] = String(value); },
      getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(node.attrs, name)
          ? node.attrs[name] : null;
      },
      get firstChild() { return node.childNodes[0] || null; },
      get children() { return node.childNodes.filter((c) => c.nodeType === 1); },
      get lastElementChild() {
        const k = node.children; return k.length ? k[k.length - 1] : null;
      },
      // Real DOM leaves no children at all for "", which is how renderMarkdown
      // clears its container; a lone empty text node instead would show up in
      // the serializer's output and in every anchor offset.
      set textContent(v) {
        for (const c of node.childNodes) c.parentNode = null;
        node.childNodes = [];
        if (String(v) !== "") node.appendChild(text(v));
      },
      get textContent() {
        return node.childNodes.map((c) =>
          c.nodeType === 3 ? c.nodeValue : c.textContent).join("");
      },
    };
    return node;
  };
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
    "\nreturn { splitBlocks, blockKind, renderMarkdown, docTextAndMap, locateAnchor," +
    " segmentsFor, normalize, serialize, fnv1a };");
  return factory(makeShim());
}

module.exports = { loadModule, makeShim, TEMPLATE };
