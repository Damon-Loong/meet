import { useTelephony } from './useTelephony'
import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useState } from 'react'
import { formatPinCode } from '@/features/rooms/utils/telephony'
import type { ApiRoom } from '@/features/rooms/api/ApiRoom'
import { getRouteUrl } from '@/navigation/getRouteUrl'
import { reportError } from '@/features/analytics/telemetry'
import { useUser } from '@/features/auth/api/useUser'

const COPY_SUCCESS_TIMEOUT = 3000

export const useCopyRoomToClipboard = (room: ApiRoom | undefined) => {
  const telephony = useTelephony()
  const { t } = useTranslation('global', { keyPrefix: 'clipboardContent' })
  const { user } = useUser()

  const [isCopied, setIsCopied] = useState(false)
  const [isRoomUrlCopied, setIsRoomUrlCopied] = useState(false)

  useEffect(() => {
    if (isCopied) {
      const timeout = setTimeout(() => setIsCopied(false), COPY_SUCCESS_TIMEOUT)
      return () => clearTimeout(timeout)
    }
  }, [isCopied])

  useEffect(() => {
    if (isRoomUrlCopied) {
      const timeout = setTimeout(
        () => setIsRoomUrlCopied(false),
        COPY_SUCCESS_TIMEOUT
      )
      return () => clearTimeout(timeout)
    }
  }, [isRoomUrlCopied])

  const roomSlug = room?.slug
  const roomUrl = useMemo(() => {
    return roomSlug ? getRouteUrl('room', roomSlug) : ''
  }, [roomSlug])

  const hasTelephonyInfo = useMemo(() => {
    return telephony.enabled && room?.pin_code
  }, [telephony.enabled, room])

  const copyRoomToClipboard = async (subject = '') => {
    try {
      if (!roomUrl || !room) return

      const inviter = user?.full_name || user?.email || t('defaultInviter')
      const startTime = new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(new Date())

      const content = [
        t('invitation', { inviter }),
        subject ? t('subject', { subject }) : undefined,
        t('startTime', { startTime }),
        t('url', { roomUrl }),
        hasTelephonyInfo
          ? t('numberAndPin', {
              phoneNumber: telephony?.internationalPhoneNumber,
              pinCode: formatPinCode(room.pin_code),
            })
          : undefined,
      ]
        .filter(Boolean)
        .join('\n')

      await navigator.clipboard.writeText(content)
      setIsCopied(true)
    } catch (error) {
      reportError('clipboard_failure', error, {
        context: 'copy_room_content',
      })
    }
  }

  const copyRoomUrlToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(roomUrl)
      setIsRoomUrlCopied(true)
    } catch (error) {
      reportError('clipboard_failure', error, {
        context: 'copy_room_url',
      })
    }
  }

  return {
    isCopied,
    copyRoomToClipboard,
    isRoomUrlCopied,
    copyRoomUrlToClipboard,
  }
}
