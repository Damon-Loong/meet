import { RiMicLine, RiVolumeUpLine } from '@remixicon/react'
import { MenuItem } from 'react-aria-components'
import { menuRecipe } from '@/primitives/menuRecipe'
import { useAudioRecovery } from '../../../hooks/useAudioRecovery'

export function AudioRecoveryMenuItems() {
  const recovery = useAudioRecovery()
  const itemClass = menuRecipe({ icon: true, variant: 'dark' }).item
  return (
    <>
      <MenuItem className={itemClass} onAction={recovery.restorePlayback}>
        <RiVolumeUpLine size={20} />
        恢复声音
      </MenuItem>
      <MenuItem
        className={itemClass}
        isDisabled={!recovery.microphoneEnabled || recovery.busy}
        onAction={recovery.restoreMicrophone}
      >
        <RiMicLine size={20} />
        恢复麦克风
      </MenuItem>
    </>
  )
}
