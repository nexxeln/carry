// Renders the harness cases in Chromium, Firefox, and WebKit and compares pixels.
//
//   node tests/browser_test.mjs      # needs `uv run generate.py` first
//
// Each case is drawn on a canvas and laid out as DOM text: the typed text in
// Carry, and the expected text in Carry Plain (the same font with GSUB
// removed). Identical outlines and advances mean a correct answer is
// pixel-identical. Chrome and Firefox sanitize web fonts with OTS before
// HarfBuzz sees them, so a rejected font fails every case instead of passing.
//
// WebKit splits DOM text at an ASCII hyphen before shaping, even with
// white-space: nowrap, so `5-7=` never reaches the font whole. The DOM check
// uses word-break: keep-all, which stops the split. Plain DOM text is
// reported separately as an engine difference, not a failure. So is text with
// letter-spacing, because Chromium turns calt off whenever letter-spacing is
// not zero.
import { execFileSync } from "node:child_process"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { createServer } from "node:http"
import { extname, join } from "node:path"
import { chromium, firefox, webkit } from "playwright"

const root = new URL("..", import.meta.url).pathname
const out = join(root, "build/browser")
mkdirSync(out, { recursive: true })

execFileSync("uv", ["run", "python", "-c", `
import json, sys
sys.path.insert(0, "tests")
from fontTools.ttLib import TTFont
from test_shape import cases
font = TTFont("build/Carry.ttf")
del font["GSUB"]
font["name"].setName("Carry Plain", 1, 3, 1, 0x409)
font.save("build/browser/Carry-Plain.ttf")
meta = json.load(open("build/carry.json"))["stats"]
suite = cases(meta["maxDigits"], meta["maxMulDigits"], "+-*×", 600, 11)
json.dump(suite, open("build/browser/cases.json", "w"))
`], { cwd: root, stdio: "inherit" })

writeFileSync(join(out, "index.html"), `<!doctype html><meta charset="utf-8">
<body style="margin:0"><canvas id="c" width="1400" height="40"></canvas><div id="dom" style="font-size:24px;white-space:pre"></div>
<script type="module">
window.run = async () => {
  for (const [family, file] of [["Carry", "/Carry.ttf"], ["Carry Plain", "/browser/Carry-Plain.ttf"]]) {
    const face = new FontFace(family, "url(" + file + ")")
    document.fonts.add(await face.load())
  }
  const cases = await (await fetch("/browser/cases.json")).json()
  const ctx = document.getElementById("c").getContext("2d", { willReadFrequently: true })
  const dom = document.getElementById("dom")
  const draw = (family, text) => {
    ctx.clearRect(0, 0, 1400, 40)
    ctx.font = "24px '" + family + "'"
    ctx.fillText(text, 2, 30)
    return ctx.getImageData(0, 0, 1400, 40).data
  }
  const domWidth = (family, text, keepAll = true, letterSpacing = "normal") => {
    const span = document.createElement("span")
    span.style.fontFamily = "'" + family + "'"
    span.style.letterSpacing = letterSpacing
    if (keepAll) span.style.wordBreak = "keep-all"
    span.textContent = text
    dom.replaceChildren(span)
    return span.getBoundingClientRect().width
  }
  const failures = []
  let splitDom = 0
  let spaced = 0
  for (const [typed, want] of cases) {
    const a = draw("Carry", typed)
    const b = draw("Carry Plain", want)
    let same = a.length === b.length
    for (let i = 0; same && i < a.length; i++) same = a[i] === b[i]
    const widths = [domWidth("Carry", typed), domWidth("Carry Plain", want)]
    if (!same || Math.abs(widths[0] - widths[1]) > 0.01) failures.push({ typed, want, canvas: same, widths })
    if (Math.abs(domWidth("Carry", typed, false) - widths[1]) > 0.01) splitDom++
    // Spacing is added per character, and the answer belongs to the = character,
    // so compare against the typed text without its answer: equal widths mean
    // the answer vanished.
    const computes = typed !== want
    if (computes && Math.abs(domWidth("Carry", typed, true, "1px") - domWidth("Carry Plain", typed, true, "1px")) < 0.01) spaced++
  }
  return { total: cases.length, failures, splitDom, spaced }
}
</script>`)

const types = { ".html": "text/html", ".ttf": "font/ttf", ".json": "application/json" }
const server = createServer((req, res) => {
  try {
    const path = join(root, "build", decodeURIComponent(req.url === "/" ? "/browser/index.html" : req.url))
    const body = readFileSync(path)
    res.writeHead(200, { "content-type": types[extname(path)] ?? "application/octet-stream" })
    res.end(body)
  } catch {
    res.writeHead(404).end()
  }
}).listen(0)
const url = `http://localhost:${server.address().port}/`

let failed = false
for (const [name, engine] of [["chromium", chromium], ["firefox", firefox], ["webkit", webkit]]) {
  const browser = await engine.launch()
  const page = await browser.newPage()
  const errors = []
  page.on("console", (msg) => msg.type() === "error" && errors.push(msg.text()))
  page.on("pageerror", (err) => errors.push(String(err)))
  await page.goto(url)
  const result = await page.evaluate(() => window.run()).catch((err) => ({ total: 0, failures: [], error: String(err) }))
  const pass = result.total - result.failures.length
  console.log(`${name} ${browser.version()}: ${pass}/${result.total} pass${result.error ? ` (${result.error})` : ""}; without keep-all, ${result.splitDom} DOM cases lose their answer; with letter-spacing, ${result.spaced}`)
  for (const f of result.failures.slice(0, 8)) console.log(`  ${JSON.stringify(f)}`)
  for (const e of errors) console.log(`  console: ${e}`)
  failed ||= Boolean(result.error) || result.failures.length > 0 || result.total === 0
  await browser.close()
}
server.close()
process.exit(failed ? 1 : 0)
