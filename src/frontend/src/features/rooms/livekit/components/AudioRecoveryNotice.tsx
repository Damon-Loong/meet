import { css } from '@/styled-system/css'
import { useAudioRecovery } from '../hooks/useAudioRecovery'

/** Lives in the control-bar layout, never over the participant panel header. */
export function AudioRecoveryNotice() {
  const recovery = useAudioRecovery()
  if (!recovery.playbackBlocked && !recovery.microphoneFailed) return null

  return (
    <div
      role="status"
      aria-label="声音恢复提示"
      className={css({
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        gap: '0.5rem',
        maxWidth: 'calc(100% - 1rem)',
        marginBottom: '0.5rem',
        borderRadius: '0.75rem',
        padding: '0.25rem',
        backgroundColor: '#243044',
        color: 'white',
        '& button': {
          minHeight: '44px',
          padding: '0.5rem 0.75rem',
          borderRadius: '0.5rem',
          fontSize: '0.875rem',
          cursor: 'pointer',
          '&:focus-visible': { outline: '2px solid white' },
          '&:disabled': { opacity: 0.6 },
        },
      })}
    >
      {recovery.playbackBlocked && (
        <button type="button" onClick={recovery.restorePlayback}>
          点击恢复声音
        </button>
      )}
      {recovery.microphoneFailed && (
        <button
          type="button"
          disabled={recovery.busy}
          onClick={recovery.restoreMicrophone}
        >
          {recovery.busy ? '正在恢复麦克风…' : '点击恢复麦克风'}
        </button>
      )}
    </div>
  )
}
