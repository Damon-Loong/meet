import { useLocalParticipant, useRoomContext } from '@livekit/components-react'
import {
  ConnectionState,
  LocalAudioTrack,
  RoomEvent,
  Track,
} from 'livekit-client'
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { AudioRecoveryContext } from '../hooks/useAudioRecovery'
import { captureMediaEvent } from '@/features/analytics/telemetry'
import {
  AudioRecoveryGate,
  recoverEnabledMicrophone,
} from '../utils/audioRecovery'

/** Playback repair is separate from capture repair: listening never unmutes. */
export function AudioRecovery({ children }: { children: ReactNode }) {
  const room = useRoomContext()
  const { microphoneTrack, isMicrophoneEnabled } = useLocalParticipant()
  const [blocked, setBlocked] = useState(false)
  const [microphoneFailed, setMicrophoneFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const mounted = useRef(false)
  const micEnabled = useRef(isMicrophoneEnabled)
  micEnabled.current = isMicrophoneEnabled
  const gate = useRef(new AudioRecoveryGate())

  const restartMic = useCallback(
    async (manual: boolean) => {
      await gate.current.run(manual, async () => {
        if (mounted.current) setBusy(true)
        const canRecover = () =>
          mounted.current &&
          micEnabled.current &&
          room.state === ConnectionState.Connected &&
          document.visibilityState === 'visible'
        try {
          const getTrack = () => {
            const track = room.localParticipant.getTrackPublication(
              Track.Source.Microphone
            )?.track
            return track instanceof LocalAudioTrack ? track : undefined
          }
          // Check health only BEFORE repair. The identity lookup must still
          // return the same track after repair makes it healthy.
          const result = await recoverEnabledMicrophone(
            getTrack,
            canRecover,
            (track) =>
              manual ||
              track.mediaStreamTrack.readyState !== 'live' ||
              track.mediaStreamTrack.muted ||
              !track.mediaStreamTrack.enabled ||
              track.isUpstreamPaused
          )
          void captureMediaEvent('audio-recovery-microphone', {
            livekit_participant_sid: room.localParticipant.sid,
            manual,
            result,
          })
          if (mounted.current) setMicrophoneFailed(false)
        } catch {
          void captureMediaEvent('audio-recovery-microphone', {
            livekit_participant_sid: room.localParticipant.sid,
            manual,
            result: 'failed',
          })
          if (mounted.current) setMicrophoneFailed(micEnabled.current)
        } finally {
          if (mounted.current) setBusy(false)
        }
      })
    },
    [room]
  )

  const startPlayback = useCallback(
    (manual: boolean) => {
      // Invoke immediately inside the click, before any await, for user activation.
      void room
        .startAudio()
        .then(() => {
          if (!mounted.current) return
          setBlocked(!room.canPlaybackAudio)
          void captureMediaEvent('audio-recovery-playback', {
            livekit_participant_sid: room.localParticipant.sid,
            manual,
            allowed: room.canPlaybackAudio,
          })
        })
        .catch(() => {
          if (!mounted.current) return
          setBlocked(true)
          void captureMediaEvent('audio-recovery-playback', {
            livekit_participant_sid: room.localParticipant.sid,
            manual,
            allowed: false,
          })
        })
    },
    [room]
  )

  useEffect(() => {
    mounted.current = true
    let backgrounded = document.visibilityState !== 'visible'
    let timer: ReturnType<typeof setTimeout> | undefined
    const recover = () => {
      if (document.visibilityState !== 'visible') return
      startPlayback(false)
      clearTimeout(timer)
      timer = setTimeout(() => void restartMic(false), 700)
    }
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') {
        backgrounded = true
        clearTimeout(timer)
      } else if (backgrounded) {
        backgrounded = false
        recover()
      }
    }
    const onPlayback = () => setBlocked(!room.canPlaybackAudio)
    room.on(RoomEvent.AudioPlaybackStatusChanged, onPlayback)
    room.on(RoomEvent.Reconnected, recover)
    document.addEventListener('visibilitychange', onVisibility)
    startPlayback(false)
    return () => {
      mounted.current = false
      clearTimeout(timer)
      room.off(RoomEvent.AudioPlaybackStatusChanged, onPlayback)
      room.off(RoomEvent.Reconnected, recover)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [room, restartMic, startPlayback])

  useEffect(() => {
    if (!isMicrophoneEnabled) setMicrophoneFailed(false)
    const track = microphoneTrack?.track?.mediaStreamTrack
    if (!track) return
    let timer: ReturnType<typeof setTimeout> | undefined
    // Let a brief interruption settle before trying automatic recovery.
    // Returning from a call is also handled by visibilitychange above.
    const interrupted = () => {
      if (!micEnabled.current || document.visibilityState !== 'visible') return
      clearTimeout(timer)
      timer = setTimeout(() => void restartMic(false), 700)
    }
    track.addEventListener('ended', interrupted)
    track.addEventListener('mute', interrupted)
    return () => {
      clearTimeout(timer)
      track.removeEventListener('ended', interrupted)
      track.removeEventListener('mute', interrupted)
    }
  }, [microphoneTrack?.track, isMicrophoneEnabled, restartMic])

  return (
    <AudioRecoveryContext.Provider
      value={{
        playbackBlocked: blocked,
        microphoneFailed: microphoneFailed && isMicrophoneEnabled,
        microphoneEnabled: isMicrophoneEnabled,
        busy,
        restorePlayback: () => startPlayback(true),
        restoreMicrophone: () => void restartMic(true),
      }}
    >
      {children}
    </AudioRecoveryContext.Provider>
  )
}
