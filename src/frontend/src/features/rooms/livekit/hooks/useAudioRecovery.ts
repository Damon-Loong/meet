import { createContext, useContext } from 'react'

export interface AudioRecoveryState {
  playbackBlocked: boolean
  microphoneFailed: boolean
  microphoneEnabled: boolean
  busy: boolean
  restorePlayback: () => void
  restoreMicrophone: () => void
}

export const AudioRecoveryContext = createContext<AudioRecoveryState | null>(
  null
)

export function useAudioRecovery() {
  const value = useContext(AudioRecoveryContext)
  if (!value) throw new Error('AudioRecovery provider is required')
  return value
}
