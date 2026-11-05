export interface RecoverableMicrophone {
  isMuted: boolean
  restartTrack(): Promise<unknown>
  mute(): Promise<unknown>
}

/** Only repair an already enabled microphone. Never turn a muted mic on. */
export async function recoverEnabledMicrophone<T extends RecoverableMicrophone>(
  getTrack: () => T | undefined,
  canRecover: () => boolean,
  needsRepair: (track: T) => boolean = () => true
): Promise<'restarted' | 'skipped'> {
  const track = getTrack()
  if (!canRecover() || !track || track.isMuted || !needsRepair(track))
    return 'skipped'
  await track.restartTrack()
  // The user can mute or leave while getUserMedia is still pending.
  if (!canRecover() || track.isMuted || getTrack() !== track) {
    await track.mute()
  }
  return 'restarted'
}

/** Coalesce background/focus/device events; never overlap capture requests. */
export class AudioRecoveryGate {
  private busy = false
  private lastAttempt = -Infinity

  async run(manual: boolean, operation: () => Promise<void>): Promise<boolean> {
    if (this.busy || (!manual && Date.now() - this.lastAttempt < 5000)) {
      return false
    }
    this.busy = true
    this.lastAttempt = Date.now()
    try {
      await operation()
      return true
    } finally {
      this.busy = false
    }
  }
}
