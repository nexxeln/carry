import assert from "node:assert/strict"
import { chromium, firefox, webkit } from "playwright"

for (const [name, engine] of [["chromium", chromium], ["firefox", firefox], ["webkit", webkit]]) {
  const browser = await engine.launch()
  try {
    const page = await browser.newPage()
    await page.goto(new URL("../docs/images/hero.svg", import.meta.url).href)
    const positions = await page.evaluate(async () => {
      const animations = document.getAnimations()
      const result = []
      for (const time of [80, 240, 400, 560, 720, 880, 1040, 1200, 1360, 2000, 4600, 5220]) {
        for (const animation of animations) {
          animation.pause()
          animation.currentTime = time
        }
        await new Promise(requestAnimationFrame)
        const carets = [...document.querySelectorAll(".caret")].filter((caret) => {
          for (let node = caret.parentElement; node; node = node.parentElement) {
            if (Number(getComputedStyle(node).opacity) === 0) return false
          }
          return true
        })
        result.push(carets.map((caret) => Math.round(caret.getBBox().x * 10) / 10))
      }
      return result
    })
    assert.deepEqual(positions, [[25.6], [109.6], [181.6], [253.6], [325.6], [397.6], [469.6], [541.6], [829.6], [829.6], [25.6], [109.6]])
    await page.emulateMedia({ reducedMotion: "reduce" })
    const reduced = await page.evaluate(() => ({
      visible: [...document.querySelectorAll(".frame")].filter((frame) => getComputedStyle(frame).opacity === "1").map((frame) => frame.classList.contains("last")),
      steady: [...document.querySelectorAll(".frame, .caret")].every((node) => getComputedStyle(node).animationName === "none"),
    }))
    assert.deepEqual(reduced, { visible: [true], steady: true })
    console.log(`${name} caret follows typing, resets on repeat, and respects reduced motion`)
  } finally {
    await browser.close()
  }
}
