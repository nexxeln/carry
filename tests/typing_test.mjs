// Types expressions key by key into a textarea set in Carry, in Chromium,
// Firefox, and WebKit, and checks that the answer is drawn after every edit.
//
//   node tests/typing_test.mjs [font.ttf]     # default build/Carry.ttf; run tests/browser_test.mjs once first
//
// In an edit, ⌫ presses Backspace and ← presses the left arrow.
//
// Setting a textarea's value in one go shapes the whole line from scratch.
// Typing does not: an engine may keep the shaping of the text before the edit
// and reshape only from the last point HarfBuzz marked safe to break.
import { readFileSync } from "node:fs"
import { chromium, firefox, webkit } from "playwright"

const font = readFileSync(process.argv[2] ?? new URL("../build/Carry.ttf", import.meta.url).pathname).toString("base64")
const plain = readFileSync(new URL("../build/browser/Carry-Plain.ttf", import.meta.url)).toString("base64")
const meta = JSON.parse(readFileSync(new URL("../build/carry.json", import.meta.url))).stats
// [keys pressed, text the textarea should then hold, text the font should draw]
const edits = [
  ["1+1=", "1+1=", "1+1=2"],
  ["128+256=", "128+256=", "128+256=384"],
  ["5-7=", "5-7=", "5-7=-2"],
  ["12×34=", "12×34=", "12×34=408"],
  ["1+1=2", "1+1=2", "1+1=2"],
  ["1.5+2=", "1.5+2=", meta.maxFractionDigits ? "1.5+2=3.5" : "1.5+2="],
  ["1+1=2⌫", "1+1=", "1+1=2"],
  ["12+5=←←0", "12+05=", "12+05=17"],
  ["999+1=←←←←⌫8", "989+1=", "989+1=990"],
]
if (meta.arithmeticStage) edits.push(
  ["128 + 256 =", "128 + 256 =", "128 + 256 =384"],
  ["-5+7=", "-5+7=", "-5+7=2"],
  ["5×-7=", "5×-7=", "5×-7=-35"],
  ["-5--7=", "-5--7=", "-5--7=2"],
  ["-5+7=←←←←⌫", "5+7=", "5+7=12"],
  ["1+2= 3", "1+2= 3", "1+2= 3"],
  ["1 + 2 = -3", "1 + 2 = -3", "1 + 2 = -3"],
  ["1+2=\u00a0+3", "1+2=\u00a0+3", "1+2=\u00a0+3"],
  ["1+2= 3⌫", "1+2= ", "1+2=3 "],
)
if (meta.maxFractionDigits) edits.push(
  ["0.1+0.2=", "0.1+0.2=", "0.1+0.2=0.3"],
  ["19.99×3=", "19.99×3=", "19.99×3=59.97"],
  ["1.5+2=←←←←⌫", "15+2=", "15+2=17"],
)
if (meta.maxDivDigits) edits.push(
  ["84÷7=", "84÷7=", "84÷7=12"],
  ["17/5=", "17/5=", "17/5=3 r 2"],
  ["5/0=", "5/0=", "5/0="],
  ["17/5=←⌫2", "17/2=", "17/2=8 r 1"],
)

let failed = false
for (const [name, engine] of [["chromium", chromium], ["firefox", firefox], ["webkit", webkit]]) {
  const browser = await engine.launch()
  const page = await browser.newPage({ viewport: { width: 900, height: 300 } })
  await page.setContent(`<style>
    @font-face { font-family: Carry; src: url(data:font/ttf;base64,${font}); }
    @font-face { font-family: Plain; src: url(data:font/ttf;base64,${plain}); }
    textarea { font: 40px Carry; width: 800px; height: 70px; padding: 8px; border: 0; outline: none; resize: none; word-break: keep-all; caret-color: transparent; background: #fff; color: #000; }
  </style><textarea rows="1" wrap="off" spellcheck="false"></textarea>`)
  await page.evaluate(() => Promise.all([document.fonts.load("40px Carry"), document.fonts.load("40px Plain")]))
  const box = page.locator("textarea")
  const results = []
  for (const [typed, value, want] of edits) {
    if (name === "firefox" && typed.includes("\u00a0")) continue
    await box.click()
    await page.keyboard.press("ControlOrMeta+A")
    await page.keyboard.press("Backspace")
    for (const key of typed) {
      if (key === "⌫") await page.keyboard.press("Backspace")
      else if (key === "←") await page.keyboard.press("ArrowLeft")
      else await page.keyboard.type(key)
      await page.waitForTimeout(30)
    }
    await page.waitForTimeout(100)
    const actual = await box.screenshot()
    await box.evaluate((el, text) => {
      el.dataset.typed = el.value
      el.style.fontFamily = "Plain"
      el.value = text
    }, want)
    const reference = await box.screenshot()
    await box.evaluate((el) => {
      el.style.fontFamily = ""
      el.value = el.dataset.typed
    })
    const held = await box.inputValue()
    const ok = held === value && actual.equals(reference)
    failed ||= !ok
    results.push(`${typed} ${held !== value ? `HOLDS ${held}` : ok ? "ok" : "WRONG"}`)
  }
  console.log(`${name.padEnd(9)} ${results.join("  ")}`)
  await browser.close()
}
process.exit(failed ? 1 : 0)
