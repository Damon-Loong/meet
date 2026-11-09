// Offline regression fixture. No connection, device capture, recording or mail.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { RoomContext } from '@livekit/components-react'
import {
  Room,
  RoomEvent,
  ConnectionState,
  LocalAudioTrack,
  LocalTrackPublication,
  ParticipantEvent,
  Track,
} from 'livekit-client'
import { TrackInfo, TrackSource } from '@livekit/protocol'
import { Menu as RACMenu, MenuSection } from 'react-aria-components'
import { Button, Menu } from '../src/primitives'
import { AudioRecovery } from '../src/features/rooms/livekit/components/AudioRecovery'
import { AudioRecoveryNotice } from '../src/features/rooms/livekit/components/AudioRecoveryNotice'
import { AudioRecoveryMenuItems } from '../src/features/rooms/livekit/components/controls/Options/AudioRecoveryMenuItems'
import { AudioRecoveryButtons } from '../src/features/rooms/livekit/components/controls/Options/AudioRecoveryButtons'
import { ResponsiveMenu } from '../src/features/rooms/livekit/prefabs/ControlBar/ResponsiveMenu'
import '../src/styles/index.css'

const room = new Room()
room.state = ConnectionState.Connected
let blocked = new URLSearchParams(location.search).has('blocked')
let broken = false
let failMic = false
let restarts = 0
let playbackCalls = 0
Object.defineProperty(room, 'canPlaybackAudio', { get: () => !blocked })
room.startAudio = async () => {
  playbackCalls++
  if (blocked && !navigator.userActivation.isActive)
    throw new Error('autoplay denied')
  blocked = false
  room.emit(RoomEvent.AudioPlaybackStatusChanged, true)
}
const audio = new AudioContext()
const native = audio.createMediaStreamDestination().stream.getAudioTracks()[0]
Object.defineProperty(native, 'muted', { get: () => broken })
const track = new LocalAudioTrack(native)
track.source = Track.Source.Microphone
track.restartTrack = async () => {
  restarts++
  if (failMic) throw new Error('microphone interrupted')
  broken = false
}
const publication = new LocalTrackPublication(
  Track.Kind.Audio,
  new TrackInfo({ sid: 'test-mic', source: TrackSource.MICROPHONE }),
  track
)
room.localParticipant.audioTrackPublications.set(
  publication.trackSid,
  publication
)
room.localParticipant.trackPublications.set(publication.trackSid, publication)
const test = {
  state: () => ({ restarts, playbackCalls, muted: track.isMuted }),
  async mute(value: boolean) {
    if (value) await track.mute()
    else await track.unmute()
    room.localParticipant.emit(
      value ? ParticipantEvent.TrackMuted : ParticipantEvent.TrackUnmuted,
      publication
    )
  },
  interrupt(fail = false) {
    broken = true
    failMic = fail
    native.dispatchEvent(new Event('mute'))
  },
  allowMic() {
    failMic = false
  },
  reconnect() {
    room.emit(RoomEvent.Reconnected)
  },
}
Object.assign(window, { audioTest: test })
function Fixture() {
  const [panel, setPanel] = React.useState(true)
  const [menu, setMenu] = React.useState(false)
  const mobileMenu = new URLSearchParams(location.search).has('mobileMenu')
  return (
    <RoomContext.Provider value={room}>
      <AudioRecovery>
        <main
          style={{
            height: '100dvh',
            background: '#171722',
            color: 'white',
            position: 'relative',
            padding: 16,
          }}
        >
          <div
            style={{
              height: '60%',
              background: '#f0f2f6',
              color: '#39434f',
              borderRadius: 12,
              padding: 20,
            }}
          >
            Marsh的画面
          </div>
          {panel && (
            <section
              style={{
                position: 'absolute',
                inset: '16px 16px 100px',
                background: 'white',
                color: '#222',
                borderRadius: 12,
                padding: 24,
                zIndex: 101,
              }}
              aria-label="参会者"
            >
              <h2>参会者</h2>
              <button
                onClick={() => setPanel(false)}
                aria-label="关闭参会者"
                style={{
                  position: 'absolute',
                  right: 12,
                  top: 12,
                  width: 44,
                  height: 44,
                }}
              >
                ×
              </button>
              <p style={{ marginTop: 32 }}>Long（您）</p>
              <p>北北</p>
              <p>欧智峰</p>
            </section>
          )}
          <div
            style={{
              position: 'absolute',
              bottom: 0,
              left: 0,
              right: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
            }}
          >
            <AudioRecoveryNotice />
            <div
              id="control-bar"
              style={{ display: 'flex', gap: 12, padding: 16, zIndex: 100 }}
            >
              <Button variant="danger" aria-label="离开">
                挂断
              </Button>
              <Button
                onPress={() => void test.mute(!track.isMuted)}
                aria-label="麦克风"
              >
                麦克风
              </Button>
              <>
                {mobileMenu ? (
                  <>
                    <Button aria-label="更多" onPress={() => setMenu(true)}>
                      ⋮
                    </Button>
                    <ResponsiveMenu
                      isOpened={menu}
                      onClosed={() => setMenu(false)}
                    >
                      <div
                        style={{
                          display: 'flex',
                          gap: 16,
                          justifyContent: 'center',
                        }}
                      >
                        <AudioRecoveryButtons onClose={() => setMenu(false)} />
                      </div>
                    </ResponsiveMenu>
                  </>
                ) : (
                  <Menu variant="dark">
                    <Button aria-label="更多">⋮</Button>
                    <RACMenu style={{ width: 240 }}>
                      <MenuSection>
                        <AudioRecoveryMenuItems />
                      </MenuSection>
                    </RACMenu>
                  </Menu>
                )}
              </>
            </div>
          </div>
        </main>
      </AudioRecovery>
    </RoomContext.Provider>
  )
}
createRoot(document.getElementById('root')!).render(<Fixture />)
