import { css } from '@/styled-system/css'
import { useTranslation } from 'react-i18next'
import { useRef, useEffect } from 'react'
import { Text } from '@/primitives'
import {
  RecordingMode,
  useHasRecordingAccess,
  useRecordingStatuses,
} from '@/features/recording'
import { FeatureFlags } from '@/features/analytics/enums'
import { Button as RACButton } from 'react-aria-components'
import { useSidePanel } from '@/features/rooms/livekit/hooks/useSidePanel'
import { useRoomMetadata } from '../hooks/useRoomMetadata'
import { RecordingStatusIcon } from './RecordingStatusIcon'
import { useIsRecording } from '@livekit/components-react'
import { useScreenReaderAnnounce } from '@/hooks/useScreenReaderAnnounce'

export const RecordingStateToast = () => {
  const { t } = useTranslation('rooms', {
    keyPrefix: 'recordingStateToast',
  })

  const { openTranscript, openScreenRecording } = useSidePanel()

  const lastKeysRef = useRef({ screen: '', transcript: '' })
  const announce = useScreenReaderAnnounce()

  const hasTranscriptAccess = useHasRecordingAccess(
    RecordingMode.Transcript,
    FeatureFlags.Transcript
  )

  const hasScreenRecordingAccess = useHasRecordingAccess(
    RecordingMode.ScreenRecording,
    FeatureFlags.ScreenRecording
  )

  const {
    isStarted: isScreenRecordingStarted,
    isStarting: isScreenRecordingStarting,
    isActive: isScreenRecordingActive,
  } = useRecordingStatuses(RecordingMode.ScreenRecording)

  const { isStarted: isTranscriptStarted, isActive: isTranscriptActive } =
    useRecordingStatuses(RecordingMode.Transcript)

  const metadata = useRoomMetadata()
  const isRecording = useIsRecording()

  const screenKey =
    metadata?.recording_status &&
    metadata?.recording_mode &&
    (isScreenRecordingStarting || isScreenRecordingStarted)
      ? `${metadata.recording_mode}.${isScreenRecordingStarted && !isRecording ? 'starting' : metadata.recording_status}`
      : undefined

  const transcriptKey =
    metadata?.transcription_status && isTranscriptActive
      ? `${RecordingMode.Transcript}.${metadata.transcription_status}`
      : undefined

  // Update screen reader message only when the key actually changes
  // This prevents duplicate announcements caused by re-renders
  useEffect(() => {
    if (screenKey && screenKey !== lastKeysRef.current.screen) {
      lastKeysRef.current.screen = screenKey
      announce(t(screenKey))
    }
    if (transcriptKey && transcriptKey !== lastKeysRef.current.transcript) {
      lastKeysRef.current.transcript = transcriptKey
      announce(t(transcriptKey))
    }
  }, [announce, screenKey, transcriptKey, t])

  if (!screenKey && !transcriptKey) return null

  const hasScreenRecordingAccessAndActive =
    isScreenRecordingActive && hasScreenRecordingAccess
  const hasTranscriptAccessAndActive =
    isTranscriptActive && hasTranscriptAccess && !metadata?.transcription_status

  return (
    <>
      {/* Visual banner (without aria-live to avoid duplicate announcements) */}
      <div
        className={css({
          display: 'flex',
          position: 'fixed',
          top: '10px',
          left: '10px',
          gap: '0.5rem',
          flexWrap: 'wrap',
        })}
      >
        {screenKey && (
          <div
            className={css({
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              paddingY: '0.25rem',
              paddingX: '0.75rem 0.75rem',
              backgroundColor: 'danger.700',
              borderColor: 'white',
              border: '1px solid',
              color: 'white',
              borderRadius: '4px',
            })}
          >
            <RecordingStatusIcon
              isStarted={isScreenRecordingStarted}
              isTranscriptActive={false}
            />
            {hasScreenRecordingAccessAndActive ? (
              <RACButton
                onPress={openScreenRecording}
                className={css({
                  textStyle: 'sm !important',
                  fontWeight: '500 !important',
                  cursor: 'pointer',
                })}
              >
                {t(screenKey)}
              </RACButton>
            ) : (
              <Text
                variant="sm"
                className={css({ fontWeight: '500 !important' })}
              >
                {t(screenKey)}
              </Text>
            )}
          </div>
        )}
        {transcriptKey && (
          <div
            className={css({
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              paddingY: '0.25rem',
              paddingX: '0.75rem',
              backgroundColor: 'danger.700',
              borderColor: 'white',
              border: '1px solid',
              color: 'white',
              borderRadius: '4px',
            })}
          >
            <RecordingStatusIcon
              isStarted={isTranscriptStarted}
              isTranscriptActive={true}
            />
            {hasTranscriptAccessAndActive ? (
              <RACButton
                onPress={openTranscript}
                className={css({
                  textStyle: 'sm !important',
                  fontWeight: '500 !important',
                  cursor: 'pointer',
                })}
              >
                {t(transcriptKey)}
              </RACButton>
            ) : (
              <Text
                variant="sm"
                className={css({ fontWeight: '500 !important' })}
              >
                {t(transcriptKey)}
              </Text>
            )}
          </div>
        )}
      </div>
    </>
  )
}
