import { useConnectionState } from '@livekit/components-react'
import { ConnectionState } from 'livekit-client'
import { useEffect, useRef } from 'react'

/** Keep the screen awake while the participant is connected to a meeting. */
export const useScreenWakeLock = () => {
  const connectionState = useConnectionState()
  const wakeLockRef = useRef<WakeLockSentinel | null>(null)

  useEffect(() => {
    let isDisposed = false

    const releaseWakeLock = async () => {
      const wakeLock = wakeLockRef.current
      wakeLockRef.current = null
      if (wakeLock && !wakeLock.released) {
        await wakeLock.release().catch(() => undefined)
      }
    }

    const requestWakeLock = async () => {
      if (
        isDisposed ||
        connectionState !== ConnectionState.Connected ||
        document.visibilityState !== 'visible' ||
        !('wakeLock' in navigator) ||
        wakeLockRef.current
      ) {
        return
      }

      try {
        const wakeLock = await navigator.wakeLock.request('screen')
        if (isDisposed || connectionState !== ConnectionState.Connected) {
          await wakeLock.release().catch(() => undefined)
          return
        }

        wakeLockRef.current = wakeLock
        wakeLock.addEventListener(
          'release',
          () => {
            if (wakeLockRef.current === wakeLock) wakeLockRef.current = null
          },
          { once: true }
        )
      } catch {
        // Wake Lock is best effort (unsupported browser, battery saver, etc.).
      }
    }

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') void requestWakeLock()
    }

    if (connectionState === ConnectionState.Connected) {
      void requestWakeLock()
      document.addEventListener('visibilitychange', handleVisibilityChange)
    } else {
      void releaseWakeLock()
    }

    return () => {
      isDisposed = true
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      void releaseWakeLock()
    }
  }, [connectionState])
}
