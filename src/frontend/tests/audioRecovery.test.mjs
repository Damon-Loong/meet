import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(
  new URL(
    '../src/features/rooms/livekit/utils/audioRecovery.ts',
    import.meta.url
  ),
  'utf8'
)
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
})
const { recoverEnabledMicrophone, AudioRecoveryGate } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
)

function microphone() {
  return {
    isMuted: false,
    restarts: 0,
    mutes: 0,
    async restartTrack() {
      this.restarts++
    },
    async mute() {
      this.mutes++
      this.isMuted = true
    },
  }
}

test('never acquire a microphone for a muted listener', async () => {
  const track = microphone()
  track.isMuted = true
  assert.equal(
    await recoverEnabledMicrophone(
      () => track,
      () => true
    ),
    'skipped'
  )
  assert.equal(track.restarts, 0)
})
test('background/disconnected and absent tracks cannot start capture', async () => {
  const track = microphone()
  assert.equal(
    await recoverEnabledMicrophone(
      () => track,
      () => false
    ),
    'skipped'
  )
  assert.equal(
    await recoverEnabledMicrophone(
      () => undefined,
      () => true
    ),
    'skipped'
  )
  assert.equal(track.restarts, 0)
})
test('restart only the existing enabled track', async () => {
  const track = microphone()
  assert.equal(
    await recoverEnabledMicrophone(
      () => track,
      () => true
    ),
    'restarted'
  )
  assert.equal(track.restarts, 1)
  assert.equal(track.mutes, 0)
})

test('a repaired track becoming healthy stays unmuted', async () => {
  const track = microphone()
  let broken = true
  track.restartTrack = async () => {
    broken = false
    track.restarts++
  }
  assert.equal(
    await recoverEnabledMicrophone(
      () => track,
      () => true,
      () => broken
    ),
    'restarted'
  )
  assert.equal(track.restarts, 1)
  assert.equal(track.mutes, 0)
  assert.equal(
    await recoverEnabledMicrophone(
      () => track,
      () => true,
      () => broken
    ),
    'skipped'
  )
  assert.equal(track.restarts, 1)
})
test('mute or leave during a pending recovery remains muted', async () => {
  const track = microphone()
  let enabled = true
  track.restartTrack = async () => {
    enabled = false
  }
  await recoverEnabledMicrophone(
    () => track,
    () => enabled
  )
  assert.equal(track.mutes, 1)
})
test('a replaced capture track cannot keep transmitting after recovery', async () => {
  const track = microphone()
  let current = track
  track.restartTrack = async () => {
    current = microphone()
  }
  await recoverEnabledMicrophone(
    () => current,
    () => true
  )
  assert.equal(track.mutes, 1)
  assert.equal(current.mutes, 0)
})
test('overlapping automatic and manual events do not duplicate capture', async () => {
  const gate = new AudioRecoveryGate()
  let release
  const pending = gate.run(
    false,
    () =>
      new Promise((resolve) => {
        release = resolve
      })
  )
  assert.equal(await gate.run(true, async () => assert.fail('overlap')), false)
  release()
  await pending
  assert.equal(
    await gate.run(false, async () => assert.fail('cooldown')),
    false
  )
  assert.equal(await gate.run(true, async () => {}), true)
})
test('failed requests release the lock for an explicit retry', async () => {
  const gate = new AudioRecoveryGate()
  await assert.rejects(
    gate.run(false, async () => {
      throw Error('permission denied')
    })
  )
  assert.equal(await gate.run(true, async () => {}), true)
})
