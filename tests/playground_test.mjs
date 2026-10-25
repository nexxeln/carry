import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdirSync, readFileSync } from "node:fs"
import { createServer } from "node:http"
import { extname, resolve, sep } from "node:path"
import { fileURLToPath } from "node:url"
import { chromium, firefox, webkit } from "playwright"

const root = fileURLToPath(new URL("..", import.meta.url))
const output = resolve(root, "build/playground")
mkdirSync(output, { recursive: true })
const buildFonts = process.env.CARRY_PLAYGROUND_BUILD_FONTS === "1"
execFileSync("uv", ["run", "python", "-c", `
from fontTools.ttLib import TTFont
font = TTFont(${JSON.stringify(buildFonts ? "build/Carry.ttf" : "dist/Carry.ttf")})
del font["GSUB"]
font["name"].setName("Carry Plain", 1, 3, 1, 0x409)
font.save("build/playground/Carry-Plain.ttf")
`], { cwd: root, stdio: "inherit" })
const fonts = buildFonts ? {
  "/dist/Carry.woff2": "build/Carry.ttf",
  "/dist/Carry-Debug.woff2": "build/Carry-Debug.ttf",
} : {}
const mime = { ".html": "text/html", ".woff2": "font/woff2", ".ttf": "font/ttf", ".md": "text/plain" }
const server = createServer((req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, "http://localhost").pathname)
    const path = resolve(root, fonts[pathname] ?? `.${pathname}`)
    if (!path.startsWith(root.endsWith(sep) ? root : root + sep)) {
      res.writeHead(403).end()
      return
    }
    const body = readFileSync(path)
    res.writeHead(200, { "content-type": mime[extname(path)] ?? "application/octet-stream" })
    res.end(body)
  } catch {
    res.writeHead(404).end()
  }
})
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve))
const url = `http://127.0.0.1:${server.address().port}/docs/playground.html`

try {
  for (const [name, engine] of [["chromium", chromium], ["firefox", firefox], ["webkit", webkit]]) {
    const browser = await engine.launch()
    try {
      const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
      const errors = []
      page.on("pageerror", (error) => errors.push(String(error)))
      page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()) })
      await page.goto(url)
      await page.waitForFunction(() => document.querySelector("#font-status").dataset.state)
      assert.equal(await page.locator("#font-status").getAttribute("data-state"), "ready")
      const input = page.getByRole("textbox", { name: "Expression" })
      const source = page.locator("#source")
      assert.equal(await input.inputValue(), "128+256=")
      assert.equal(await source.textContent(), "128+256=")
      assert.match(await input.evaluate((node) => getComputedStyle(node).fontFamily), /Carry/)
      assert.equal(await input.evaluate((node) => getComputedStyle(node).wordBreak), "keep-all")

      await page.screenshot({ path: resolve(output, `${name}-desktop.png`), fullPage: true })
      for (const [label, mode, family] of [["Normal", "normal", "monospace"], ["Debug", "debug", "Carry Debug"], ["Carry", "carry", "Carry"]]) {
        const button = page.getByRole("button", { name: label, exact: true })
        await button.focus()
        await page.keyboard.press("Enter")
        assert.equal(await button.getAttribute("aria-pressed"), "true")
        assert.equal(await page.locator('.modes [aria-pressed="true"]').count(), 1)
        assert.equal(await input.getAttribute("data-mode"), mode)
        assert.ok((await input.evaluate((node) => getComputedStyle(node).fontFamily)).includes(family))
        assert.equal(await input.inputValue(), "128+256=")
        assert.equal(await source.textContent(), "128+256=")
        assert.equal(await button.evaluate((node) => getComputedStyle(node).outlineStyle), "solid")
      }

      await page.evaluate(async () => {
        const reference = new FontFace("Carry Reference", "url('/build/playground/Carry-Plain.ttf')")
        document.fonts.add(await reference.load())
      })
      for (const [name, expression, expected] of [["Unsigned", "128+256=", "128+256=384"], ["Signed", "-12+5=", "-12+5=-7"], ["Decimals", "1.25+2.5=", "1.25+2.5=3.75"], ["Division", "17÷5=", "17÷5=3 r 2"]]) {
        await page.getByRole("button", { name: new RegExp(`^${name}`) }).click()
        assert.equal(await input.inputValue(), expression)
        assert.equal(await source.textContent(), expression)
        assert.equal(await input.evaluate((node) => document.activeElement === node), true)
        const actual = await input.screenshot()
        await input.evaluate((node, text) => {
          node.style.fontFamily = "Carry Reference"
          node.value = text
        }, expected)
        const reference = await input.screenshot()
        assert.ok(actual.equals(reference), `${name} draws the exact answer`)
        await input.evaluate((node, text) => {
          node.style.fontFamily = ""
          node.value = text
        }, expression)
      }
      for (const text of ["5-7=", "1.25+2.5=\n84/7=", "<img src=x onerror=alert(1)>", ""]) {
        await input.fill(text)
        assert.equal(await source.textContent(), text)
        assert.equal(await source.locator("*").count(), 0)
      }
      await input.fill("12+3")
      await input.press("End")
      await page.keyboard.type("=")
      assert.equal(await source.textContent(), "12+3=")
      assert.equal(await input.inputValue(), "12+3=")

      await page.setViewportSize({ width: 320, height: 740 })
      await input.fill("1234567890123456+1234567890123456=")
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
      for (const button of await page.getByRole("button").all()) {
        const box = await button.boundingBox()
        assert.ok(box.x >= 0 && box.x + box.width <= 320)
        assert.ok(box.height >= 40)
      }
      assert.equal(await input.evaluate((node) => node.scrollWidth > node.clientWidth), true)
      await page.getByRole("button", { name: /^Unsigned/ }).click()
      await page.screenshot({ path: resolve(output, `${name}-mobile.png`), fullPage: true })
      assert.deepEqual(errors, [])
      console.log(`${name}: fonts, modes, keyboard focus, examples, editing, text mirror, and 320px layout pass`)

      await page.route("**/dist/Carry*.woff2", (route) => route.abort())
      await page.reload()
      await page.waitForFunction(() => document.querySelector("#font-status").dataset.state === "error")
      await page.getByRole("textbox", { name: "Expression" }).fill("12+3=")
      assert.equal(await page.locator("#source").textContent(), "12+3=")
      console.log(`${name}: missing-font message and editable fallback pass`)
    } finally {
      await browser.close()
    }
  }
} finally {
  await new Promise((resolve) => server.close(resolve))
}
