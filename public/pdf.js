// Compiles a LaTeX resume to PDF in the browser (Siglum: TeX Live 2025 in WebAssembly, MIT licence).
// The LaTeX arrives by postMessage from an Apply Seamlessly window on this same site; nothing else is read or sent.
const VERSION = "0.1.4";
const PKG = `https://cdn.jsdelivr.net/npm/@siglum/engine@${VERSION}`;
const CDN = "https://cdn.siglum.org/tl2025";
const $ = id => document.getElementById(id);
const status = (t, bad) => { $("status").textContent = t; $("status").className = bad ? "bad" : "" };
let compiler = null;
let compiling = false;            // after compiling, the engine caches its format in the background: keep "Done" on screen

async function engine() {
  if (compiler) return compiler;
  status("Loading the LaTeX engine (first time: about 45 MB)…");
  $("bar").hidden = false;
  const { SiglumCompiler } = await import(`${PKG}/+esm`);
  // Browsers only start workers from this site, so the worker's code is fetched and started from a blob URL.
  const src = await (await fetch(`${PKG}/src/worker.js`)).text();
  compiler = new SiglumCompiler({
    bundlesUrl: `${CDN}/bundles`, wasmUrl: `${CDN}/busytex.wasm`, jsUrl: `${CDN}/busytex.js`,
    workerUrl: URL.createObjectURL(new Blob([src], { type: "application/javascript" })),
    enableCtan: false,                  // no package fetching from third-party proxies: standard packages only
    onProgress: (stage, detail) => { if (compiling) status(`Preparing: ${stage}${detail ? " – " + detail : ""}`) },
    onLog: msg => console.debug("[latex]", msg),      // engine log, for troubleshooting in the browser console
  });
  await compiler.init();
  return compiler;
}

let available = null;
async function missingPackages(tex) {
  // The engine has a fixed package set (no third-party package proxy). Check the .tex's \usepackage list first,
  // so an unsupported template gets a clear answer instead of a cryptic LaTeX error.
  const used = new Set();
  for (const m of tex.replace(/(^|[^\\])%.*$/gm, "$1").matchAll(/\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}/g))
    m[1].split(",").map(x => x.trim()).filter(Boolean).forEach(x => used.add(x));
  if (!used.size) return [];
  try {
    available ||= new Set(Object.keys(await (await fetch(`${CDN}/bundles/file-manifest.json`)).json()).map(f => f.split("/").pop()));
  } catch (e) { return [] }       // can't check: just try to compile
  return [...used].filter(x => !available.has(x + ".sty"));
}

function overleafButton(tex, name) {
  const f = document.createElement("form");
  Object.assign(f, { method: "POST", action: "https://www.overleaf.com/docs", target: "_blank" });
  for (const [k, v] of [["encoded_snip", encodeURIComponent(tex)], ["snip_name", (name || "Resume").slice(0, 60)], ["engine", "pdflatex"]])
    f.append(Object.assign(document.createElement("input"), { type: "hidden", name: k, value: v }));
  f.append(Object.assign(document.createElement("button"), { type: "submit", className: "btn", textContent: "Open in Overleaf instead ↗" }));
  return f;
}

const FIT = /\\def\\fitlevel\{(\d)\}/;
function pageCount(pdf) {
  // Our template writes uncompressed page objects (\pdfobjcompresslevel=0), so pages can be counted directly.
  const text = new TextDecoder("latin1").decode(pdf);
  return (text.match(/\/Type\s*\/Page(?!s)/g) || []).length;
}

async function compile(tex, name) {
  const missing = await missingPackages(tex);
  if (missing.length) {
    status(`Your template uses ${missing.join(", ")}, which the in-browser engine doesn't include. Overleaf has every package: open it there to get the PDF.`, true);
    $("actions").replaceChildren(overleafButton(tex, name));
    $("actions").hidden = false;
    return;
  }
  compiling = true;
  try {
    const c = await engine();
    status("Compiling your resume…");
    let r;
    if (FIT.test(tex)) {
      // App template: the roomiest spacing that still fits on one page (0 = roomy ... 4 = tightest).
      for (let level = 0; level <= 4; level++) {
        status(`Fitting to one page (spacing level ${level})…`);
        r = await c.compile(tex.replace(FIT, `\\def\\fitlevel{${level}}`));
        if (!r.success || !r.pdf || pageCount(r.pdf) <= 1) break;
      }
    } else {
      r = await c.compile(tex);       // your own template: compiled exactly as written
    }
    compiling = false;
    $("bar").hidden = true;
    if (!r.success || !r.pdf) {
      status("LaTeX reported an error. The log is below; fix the .tex (or use Open in Overleaf) and try again.", true);
      $("log").hidden = false;
      $("log").textContent = String(r.log || r.error || "No log").slice(-6000);
      return;
    }
    const url = URL.createObjectURL(new Blob([r.pdf], { type: "application/pdf" }));
    const file = (name || "resume").replace(/[^\w.-]+/g, "_").slice(0, 60) + ".pdf";
    const a = Object.assign(document.createElement("a"), { href: url, download: file, className: "btn", textContent: "Download PDF" });
    $("actions").replaceChildren(a);
    $("actions").hidden = false;
    $("view").src = url;
    $("view").hidden = false;
    status("Done. Check the preview, then download.");
  } catch (e) {
    compiling = false;
    $("bar").hidden = true;
    status("Couldn't make the PDF here (" + (e && e.message || e) + "). Use Open in Overleaf instead.", true);
  }
}

addEventListener("message", e => {
  if (e.origin !== location.origin || !e.data || typeof e.data.tex !== "string") return;
  compile(e.data.tex.slice(0, 60000), String(e.data.name || ""));
});
if (window.opener) window.opener.postMessage("pdf-ready", location.origin);
else status("Open this page from Resume Lab → LaTeX / PDF → PDF in browser.");
