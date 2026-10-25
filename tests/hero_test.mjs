import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { chromium, firefox, webkit } from "playwright"

const scenes = [
  ["Integer addition", "128+256=", "128+256=384"],
  ["Signed subtraction", "5 - 7 =", "5 - 7 =-2"],
  ["Signed multiplication", "-5×-7=", "-5×-7=35"],
  ["Decimal addition", "12.50+3.75=", "12.50+3.75=16.25"],
  ["Exact decimals", "0.1+0.2=", "0.1+0.2=0.3"],
  ["Decimal multiplication", "19.99×3=", "19.99×3=59.97"],
  ["Four fractional places", "0.01×0.01=", "0.01×0.01=0.0001"],
  ["Exact division", "84÷7=", "84÷7=12"],
  ["Quotient + remainder", "-17/5=", "-17/5=-3 r -2"],
]
const bitmaps = JSON.parse(execFileSync("uv", ["run", "python", "-c", "import json; from pixels import BITMAPS; print(json.dumps(BITMAPS))"], {
  cwd: fileURLToPath(new URL("../", import.meta.url)),
  encoding: "utf8",
}))

function close(actual, expected, label) {
  assert.ok(Number.isFinite(actual) && Math.abs(actual - expected) < 0.001, `${label}: expected ${expected}, got ${actual}`)
}

function sortCells(cells) {
  return cells.sort(([ac, ar], [bc, br]) => ac - bc || ar - br)
}

function literalCells(text) {
  const cells = []
  for (const [index, char] of [...text].entries()) {
    assert.ok(bitmaps[char], `Missing bitmap for ${JSON.stringify(char)}`)
    for (const [row, line] of bitmaps[char].entries()) {
      for (const [column, dot] of [...line].entries()) {
        if (dot === "#") cells.push([index * 6 + column, row])
      }
    }
  }
  return sortCells(cells)
}

function pathCells(path, label) {
  const tokenPattern = /[a-zA-Z]|[-+]?(?:\d*\.?\d+)(?:[eE][-+]?\d+)?/g
  assert.equal(path.replace(tokenPattern, "").replace(/[\s,]/g, ""), "", `${label}: invalid path tokens`)
  const tokens = (path.match(tokenPattern) ?? []).map((token) => /^[a-zA-Z]$/.test(token) ? token : Number(token))
  assert.equal(tokens.length % 19, 0, `${label}: each dot must contain one move and two arcs`)
  const cells = []
  for (let i = 0; i < tokens.length; i += 19) {
    assert.equal(tokens[i], "M", `${label}: dot move`)
    assert.deepEqual(tokens.slice(i + 3, i + 19), ["a", 4.4, 4.4, 0, 1, 0, 8.8, 0, "a", 4.4, 4.4, 0, 1, 0, -8.8, 0], `${label}: dot radius`)
    const column = (tokens[i + 1] - 25.6) / 12
    const row = (tokens[i + 2] - 62) / 12
    close(column, Math.round(column), `${label}: dot column`)
    close(row, Math.round(row), `${label}: dot row`)
    cells.push([Math.round(column), Math.round(row)])
  }
  return sortCells(cells)
}

async function sample(page, times) {
  return page.evaluate(async (times) => {
    const frames = [...document.querySelectorAll(".frame")]
    const animations = document.getAnimations()
    for (const animation of animations) animation.pause()
    await Promise.all(animations.map((animation) => animation.ready))
    const states = []
    for (const time of times) {
      for (const animation of animations) animation.currentTime = time
      await new Promise(requestAnimationFrame)
      const opacities = frames.map((frame) => getComputedStyle(frame).opacity)
      const visible = frames.flatMap((frame, index) => {
        if (Number(opacities[index]) === 0) return []
        const caption = frame.querySelector(".caption")
        const paths = [...frame.querySelectorAll(".lit")]
        const hidden = [...frame.querySelectorAll(".caption, .lit, .caret")].filter((element) => {
          for (let node = element; node; node = node.parentElement) {
            const style = getComputedStyle(node)
            if (style.display === "none" || style.visibility !== "visible" || Number(style.opacity) !== 1) return true
          }
          return false
        }).map((element) => element.getAttribute("class"))
        return [{
          index,
          scene: frame.getAttribute("data-scene"),
          typed: frame.getAttribute("data-typed"),
          last: frame.classList.contains("last"),
          caption: caption?.textContent,
          captionTag: caption?.tagName,
          hidden,
          paths: paths.map((path) => ({
            tag: path.tagName,
            d: path.getAttribute("d"),
            nestedGlow: path.parentElement !== frame && path.parentElement.tagName === "g" && getComputedStyle(path.parentElement).filter !== "none",
          })),
          carets: [...frame.querySelectorAll(".caret")].map((caret) => {
            const style = getComputedStyle(caret)
            const box = caret.getBBox()
            return { tag: caret.tagName, fill: style.fill, animation: style.animationName, opacity: style.opacity, x: box.x, y: box.y, width: box.width, height: box.height }
          }),
        }]
      })
      states.push({ time, opacities, visible })
    }
    return { animationCount: animations.length, states }
  }, times)
}

function checkFrame(frame, scene, typed, label) {
  const [caption, expression, result] = scenes[scene]
  const drawn = typed === expression ? result : typed
  assert.equal(frame.scene, String(scene), `${label}: scene`)
  assert.equal(frame.typed, typed, `${label}: typed prefix`)
  assert.equal(frame.captionTag, "text", `${label}: caption element`)
  assert.equal(frame.caption, caption, `${label}: caption`)
  assert.deepEqual(frame.hidden, [], `${label}: visible contents`)
  assert.equal(frame.paths.length, 1, `${label}: lit path count`)
  const cells = []
  for (const path of frame.paths) {
    assert.equal(path.tag, "path", `${label}: lit element`)
    assert.equal(path.nestedGlow, true, `${label}: lit path has its own glow group`)
    cells.push(...pathCells(path.d, label))
  }
  assert.deepEqual(sortCells(cells), literalCells(drawn), `${label}: every lit dot must match ${JSON.stringify(drawn)}`)
  assert.equal(frame.carets.length, 1, `${label}: caret count`)
  const [caret] = frame.carets
  assert.deepEqual({ tag: caret.tag, fill: caret.fill, animation: caret.animation, opacity: caret.opacity }, {
    tag: "rect", fill: "rgb(255, 107, 53)", animation: "none", opacity: "1",
  }, `${label}: solid orange caret`)
  close(caret.x, typed ? 25.6 + 12 * (6 * drawn.length + 1) : 25.6, `${label}: caret x`)
  close(caret.y, 57.6, `${label}: caret y`)
  close(caret.width, 56.8, `${label}: caret width`)
  close(caret.height, 80.8, `${label}: caret height`)
}

for (const [name, engine] of [["chromium", chromium], ["firefox", firefox], ["webkit", webkit]]) {
  const browser = await engine.launch()
  try {
    const page = await browser.newPage({ reducedMotion: "no-preference" })
    await page.goto(new URL("../docs/images/hero.svg", import.meta.url).href)
    const metadata = await page.evaluate(() => {
      const svg = document.documentElement
      const viewBox = svg.viewBox.baseVal
      const inverse = svg.getScreenCTM().inverse()
      const overflow = [...svg.querySelectorAll("path, rect, text")].filter((node) => !node.closest("defs")).flatMap((node) => {
        const box = node.getBBox()
        const matrix = inverse.multiply(node.getScreenCTM())
        const corners = [[box.x, box.y], [box.x + box.width, box.y], [box.x, box.y + box.height], [box.x + box.width, box.y + box.height]]
          .map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix))
        return corners.some(({ x, y }) => x < viewBox.x - 0.01 || y < viewBox.y - 0.01 || x > viewBox.x + viewBox.width + 0.01 || y > viewBox.y + viewBox.height + 0.01)
          ? [{ tag: node.tagName, class: node.getAttribute("class"), bounds: { x: box.x, y: box.y, width: box.width, height: box.height } }]
          : []
      })
      return {
        duration: svg.getAttribute("data-duration"),
        scripts: svg.querySelectorAll("script").length,
        handlers: [...svg.querySelectorAll("*")].flatMap((node) => [...node.attributes].filter((attr) => /^on/i.test(attr.name)).map((attr) => attr.name)),
        overflow,
        frames: [...svg.querySelectorAll(".frame")].map((frame, index) => ({
          index, tag: frame.tagName, scene: frame.getAttribute("data-scene"), typed: frame.getAttribute("data-typed"), start: frame.getAttribute("data-start"), stop: frame.getAttribute("data-stop"),
        })),
      }
    })
    const duration = Number(metadata.duration)
    assert.ok(metadata.duration !== null && Number.isFinite(duration) && duration >= 30, `${name}: full cycle must last at least 30 seconds`)
    assert.equal(metadata.scripts, 0, `${name}: the SVG must not run JavaScript`)
    assert.deepEqual(metadata.handlers, [], `${name}: the SVG must not contain event handlers`)
    assert.deepEqual(metadata.overflow, [], `${name}: geometry must fit inside the SVG`)
    const frames = metadata.frames.map((frame) => {
      assert.equal(frame.tag, "g", `${name}: frame ${frame.index} element`)
      assert.ok(frame.scene !== null && /^\d+$/.test(frame.scene) && Number(frame.scene) < scenes.length, `${name}: frame ${frame.index} scene`)
      assert.notEqual(frame.typed, null, `${name}: frame ${frame.index} typed metadata`)
      assert.ok(frame.start !== null && frame.stop !== null, `${name}: frame ${frame.index} timing metadata`)
      const start = Number(frame.start)
      const stop = Number(frame.stop)
      assert.ok(Number.isFinite(start) && Number.isFinite(stop) && start >= 0 && stop > start && stop <= duration + 0.001, `${name}: frame ${frame.index} interval`)
      return { ...frame, scene: Number(frame.scene), start, stop }
    })
    assert.ok(frames.length > 0, `${name}: frames exist`)
    const timeline = [...frames].sort((a, b) => a.start - b.start)
    close(timeline[0].start, 0, `${name}: timeline begins at zero`)
    close(timeline.at(-1).stop, duration, `${name}: timeline fills the full cycle`)
    for (let i = 1; i < timeline.length; i++) close(timeline[i].start, timeline[i - 1].stop, `${name}: no gap or overlap before frame ${timeline[i].index}`)
    let sceneStart = 0
    for (const [scene, [, expression]] of scenes.entries()) {
      const typed = timeline.filter((frame) => frame.scene === scene && frame.typed !== "")
      assert.deepEqual(typed.map((frame) => frame.typed), [...expression].map((_, index) => expression.slice(0, index + 1)), `${name}: scene ${scene} types every prefix exactly once`)
      for (const [index, frame] of typed.entries()) {
        close(frame.start, sceneStart + 0.16 * (index + 1), `${name}: scene ${scene} key ${index + 1}`)
        close(frame.stop - frame.start, index === typed.length - 1 ? 2.4 : 0.16, `${name}: scene ${scene} frame duration`)
      }
      sceneStart = typed.at(-1).stop + 0.4
    }
    close(duration, sceneStart, `${name}: the cycle includes every scene's result hold and rest`)
    const sampled = await sample(page, [...frames.map((frame) => (frame.start + frame.stop) * 500), duration * 1000 + 240])
    assert.ok(sampled.animationCount > 0, `${name}: normal motion animates`)
    for (const [index, state] of sampled.states.entries()) {
      const label = `${name} at ${state.time}ms`
      assert.ok(state.opacities.every((opacity) => opacity === "0" || opacity === "1"), `${label}: no partially visible frames`)
      assert.equal(state.visible.length, 1, `${label}: exactly one visible frame`)
      const expected = index < frames.length ? frames[index] : { scene: 0, typed: "1" }
      if (index < frames.length) assert.equal(state.visible[0].index, expected.index, `${label}: matching frame`)
      checkFrame(state.visible[0], expected.scene, expected.typed, label)
    }
    await page.reload()
    await page.emulateMedia({ reducedMotion: "reduce" })
    const reduced = await sample(page, [0, duration * 1000 + 240])
    assert.equal(reduced.animationCount, 0, `${name}: reduced motion has no animations`)
    assert.equal(await page.evaluate(() => [...document.querySelectorAll("*")].every((node) => getComputedStyle(node).animationName === "none")), true, `${name}: reduced motion disables CSS animations`)
    for (const state of reduced.states) {
      assert.ok(state.opacities.every((opacity) => opacity === "0" || opacity === "1"), `${name}: reduced-motion frame opacity`)
      assert.equal(state.visible.length, 1, `${name}: one reduced-motion frame`)
      assert.equal(state.visible[0].last, true, `${name}: reduced motion selects .last`)
      checkFrame(state.visible[0], scenes.length - 1, scenes.at(-1)[1], `${name}: reduced motion`)
    }
    console.log(`${name}: all ${scenes.length} scenes, ${frames.length} frame midpoints, exact bitmap dots, steady carets, loop restart, and reduced motion pass`)
  } finally {
    await browser.close()
  }
}
