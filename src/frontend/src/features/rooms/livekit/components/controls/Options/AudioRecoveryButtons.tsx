import { RiMicLine, RiVolumeUpLine } from '@remixicon/react'
import { Button } from '@/primitives/Button'
import { useAudioRecovery } from '../../../hooks/useAudioRecovery'

/** Matches the existing mobile More menu icon grid. */
export function AudioRecoveryButtons({ onClose }: { onClose: () => void }) {
  const recovery = useAudioRecovery()
  return (
    <>
      <Button
        variant="primaryTextDark"
        description
        aria-label="恢复声音"
        tooltip="恢复声音"
        onPress={() => {
          recovery.restorePlayback()
          onClose()
        }}
      >
        <RiVolumeUpLine size={20} />
      </Button>
      <Button
        variant="primaryTextDark"
        description
        aria-label="恢复麦克风"
        tooltip="恢复麦克风"
        isDisabled={!recovery.microphoneEnabled || recovery.busy}
        onPress={() => {
          recovery.restoreMicrophone()
          onClose()
        }}
      >
        <RiMicLine size={20} />
      </Button>
    </>
  )
}
