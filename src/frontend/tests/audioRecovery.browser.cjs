// Run with Vite serving the frontend; PLAYWRIGHT_MODULE may point to an external install.
const assert = require('node:assert/strict')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.AUDIO_TEST_ORIGIN || 'http://127.0.0.1:5186'
;(async () => {
  const browser = await chromium.launch({ headless: true })
  const errors = []
  let passed = 0
  async function page(query = '', width = 390) {
    const p = await browser.newPage({ viewport: { width, height: 844 } })
    p.on('pageerror', (e) => errors.push(e.message))
    await p.goto(`${origin}/tests/audioRecovery.ui.html${query}`)
    await p.waitForFunction(() => window.audioTest?.state().playbackCalls > 0)
    return p
  }
  async function closePanel(p) {
    await p.getByRole('button', { name: '关闭参会者', exact: true }).click()
    assert.equal(await p.getByRole('region', { name: '参会者' }).count(), 0)
  }
  async function noOverflow(p) {
    assert.ok(
      await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth)
    )
  }
  try {
    for (const width of [320, 390, 1280]) {
      const p = await page('', width)
      assert.equal(
        await p.getByRole('status', { name: '声音恢复提示' }).count(),
        0
      )
      assert.equal(await p.getByText('声音帮助', { exact: true }).count(), 0)
      await closePanel(p)
      await p.getByRole('button', { name: '更多', exact: true }).click()
      await p.getByRole('menuitem', { name: '恢复声音', exact: true }).click()
      assert.ok(
        (await p.evaluate(() => window.audioTest.state())).playbackCalls >= 2
      )
      assert.equal(
        (await p.evaluate(() => window.audioTest.state())).restarts,
        0
      )
      await noOverflow(p)
      await p.close()
      passed++
    }
    {
      const p = await page('?blocked')
      await closePanel(p)
      await p.getByRole('button', { name: '点击恢复声音', exact: true }).click()
      await p.waitForFunction(
        () => !document.querySelector('[aria-label="声音恢复提示"]')
      )
      assert.equal(
        (await p.evaluate(() => window.audioTest.state())).restarts,
        0
      )
      await p.close()
      passed++
    }
    {
      const p = await page()
      await p.evaluate(() => window.audioTest.interrupt())
      await p.waitForFunction(() => window.audioTest.state().restarts === 1)
      assert.equal(
        await p.getByRole('status', { name: '声音恢复提示' }).count(),
        0
      )
      await p.close()
      passed++
    }
    {
      const p = await page('?blocked', 320)
      await closePanel(p)
      await p.evaluate(() => window.audioTest.interrupt(true))
      await p
        .getByRole('button', { name: '点击恢复麦克风', exact: true })
        .waitFor()
      await noOverflow(p)
      await p.screenshot({ path: '/tmp/meet-audio-ui-failure.png' })
      await p.evaluate(() => window.audioTest.allowMic())
      await p
        .getByRole('button', { name: '点击恢复麦克风', exact: true })
        .click()
      await p.waitForFunction(() => window.audioTest.state().restarts === 2)
      await p
        .getByRole('button', { name: '点击恢复麦克风', exact: true })
        .waitFor({ state: 'detached' })
      await p.getByRole('button', { name: '点击恢复声音', exact: true }).click()
      await p.waitForFunction(
        () => !document.querySelector('[aria-label="声音恢复提示"]')
      )
      await p.close()
      passed++
    }
    {
      const p = await page()
      await closePanel(p)
      await p.evaluate(() => window.audioTest.mute(true))
      await p.evaluate(() => {
        window.audioTest.interrupt()
        window.audioTest.reconnect()
      })
      await p.waitForTimeout(1000)
      assert.equal(
        (await p.evaluate(() => window.audioTest.state())).restarts,
        0
      )
      assert.equal(
        (await p.evaluate(() => window.audioTest.state())).muted,
        true
      )
      await p.getByRole('button', { name: '更多', exact: true }).click()
      assert.equal(
        await p
          .getByRole('menuitem', { name: '恢复麦克风', exact: true })
          .getAttribute('aria-disabled'),
        'true'
      )
      await p.getByRole('menuitem', { name: '恢复声音', exact: true }).click()
      assert.equal(
        (await p.evaluate(() => window.audioTest.state())).muted,
        true
      )
      await p.close()
      passed++
    }
    {
      const p = await page('?mobileMenu', 320)
      await closePanel(p)
      await p.getByRole('button', { name: '更多', exact: true }).click()
      await p.getByRole('button', { name: '恢复声音', exact: true }).click()
      await p.getByRole('dialog').waitFor({ state: 'detached' })
      assert.ok(
        (await p.evaluate(() => window.audioTest.state())).playbackCalls >= 2
      )
      await p.evaluate(() => window.audioTest.mute(true))
      await p.getByRole('button', { name: '更多', exact: true }).click()
      assert.equal(
        await p
          .getByRole('button', { name: '恢复麦克风', exact: true })
          .isDisabled(),
        true
      )
      await p.waitForTimeout(300)
      await p.screenshot({ path: '/tmp/meet-audio-ui-mobile-menu.png' })
      await noOverflow(p)
      await p.close()
      passed++
    }
    assert.deepEqual(errors, [])
    console.log(`${passed} browser scenarios passed; no page errors`)
  } finally {
    await browser.close()
  }
})().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
