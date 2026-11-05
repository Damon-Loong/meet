import { useLocalParticipant, useRoomContext } from '@livekit/components-react'
import {
  ConnectionState,
  LocalAudioTrack,
  RoomEvent,
  Track,
} from 'livekit-client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { css } from '@/styled-system/css'
import { captureMediaEvent } from '@/features/analytics/telemetry'
import {
  AudioRecoveryGate,
  recoverEnabledMicrophone,
} from '../utils/audioRecovery'

/** Playback repair is separate from capture repair: listening never unmutes. */
export function AudioRecovery() {
  const room = useRoomContext()
  const { microphoneTrack, isMicrophoneEnabled } = useLocalParticipant()
  const [blocked, setBlocked] = useState(!room.canPlaybackAudio)
  const [expanded, setExpanded] = useState(false)
  const [message, setMessage] = useState('')
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
          if (mounted.current && manual)
            setMessage(
              result === 'restarted'
                ? '已重新连接麦克风，请说话确认。'
                : '麦克风未开启或会议尚未连接，请先检查开麦状态。'
            )
        } catch {
          void captureMediaEvent('audio-recovery-microphone', {
            livekit_participant_sid: room.localParticipant.sid,
            manual,
            result: 'failed',
          })
          if (mounted.current) {
            setExpanded(true)
            setMessage('麦克风恢复失败，请结束电话后重试，并检查麦克风权限。')
          }
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
          if (manual)
            setMessage(
              '已尝试恢复播放，请确认是否能听到声音；仍无声时检查音量及蓝牙耳机。'
            )
        })
        .catch(() => {
          if (!mounted.current) return
          setBlocked(true)
          void captureMediaEvent('audio-recovery-playback', {
            livekit_participant_sid: room.localParticipant.sid,
            manual,
            allowed: false,
          })
          if (manual)
            setMessage('声音尚未恢复，请返回会议页面后再次点击恢复声音。')
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
    const track = microphoneTrack?.track?.mediaStreamTrack
    if (!track) return
    // Native interruption is different from the user's mute button.
    const interrupted = () => {
      if (micEnabled.current) {
        setExpanded(true)
        setMessage('麦克风被中断，返回会议后可点击恢复麦克风。')
      }
    }
    track.addEventListener('ended', interrupted)
    track.addEventListener('mute', interrupted)
    return () => {
      track.removeEventListener('ended', interrupted)
      track.removeEventListener('mute', interrupted)
    }
  }, [microphoneTrack?.track])

  return (
    <aside
      aria-label="会议声音帮助"
      className={css({
        position: 'absolute',
        top: '0.5rem',
        right: '0.5rem',
        zIndex: 110,
        maxWidth: 'min(22rem, calc(100vw - 1rem))',
        borderRadius: '0.75rem',
        backgroundColor: '#17283e',
        color: 'white',
        padding: '0.5rem',
        boxShadow: '0 2px 8px #0004',
        fontSize: '0.875rem',
        '& button': {
          padding: '0.5rem',
          borderRadius: '0.375rem',
          cursor: 'pointer',
          border: '1px solid currentColor',
          margin: '0.125rem',
          '&:focus-visible': {
            outline: '2px solid white',
            outlineOffset: '2px',
          },
          '&:disabled': { opacity: 0.5, cursor: 'wait' },
        },
      })}
    >
      {blocked && (
        <button type="button" onClick={() => startPlayback(true)}>
          点击恢复声音
        </button>
      )}
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? '收起声音帮助' : '声音帮助'}
      </button>
      {expanded && (
        <div>
          {!blocked && (
            <button type="button" onClick={() => startPlayback(true)}>
              听不到声音？恢复播放
            </button>
          )}
          <button
            type="button"
            disabled={busy || !isMicrophoneEnabled}
            onClick={() => void restartMic(true)}
          >
            {busy ? '正在恢复麦克风…' : '恢复麦克风'}
          </button>
          {!isMicrophoneEnabled && <p>麦克风已关闭；需要发言时请先开麦。</p>}
          <p role="status">
            {message || '恢复播放不会打开麦克风，无需退出会议。'}
          </p>
        </div>
      )}
    </aside>
  )
}
