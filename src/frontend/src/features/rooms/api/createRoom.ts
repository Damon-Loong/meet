import { useMutation, UseMutationOptions } from '@tanstack/react-query'
import { fetchApi } from '@/api/fetchApi'
import type { ApiError } from '@/api/ApiError'
import type { ApiRoom } from './ApiRoom'

export interface CreateRoomParams {
  slug: string
  topic: string
  callbackId?: string
  username?: string
  roomType?: 'instant' | 'scheduled'
  isPermanent?: boolean
  scheduledStart?: string
  scheduledEnd?: string
  inviteEmails?: string[]
}

const createRoom = ({
  slug,
  topic,
  callbackId,
  username = '',
  roomType = 'instant',
  isPermanent = false,
  scheduledStart,
  scheduledEnd,
  inviteEmails = [],
}: CreateRoomParams): Promise<ApiRoom> => {
  return fetchApi(`rooms/?username=${encodeURIComponent(username)}`, {
    method: 'POST',
    body: JSON.stringify({
      name: slug,
      topic,
      callback_id: callbackId,
      room_type: roomType,
      is_permanent: isPermanent,
      scheduled_start: scheduledStart,
      scheduled_end: scheduledEnd,
      scheduled_timezone: 'Asia/Shanghai',
      invite_emails: inviteEmails,
    }),
  })
}

export function useCreateRoom(
  options?: UseMutationOptions<ApiRoom, ApiError, CreateRoomParams>
) {
  return useMutation<ApiRoom, ApiError, CreateRoomParams>({
    mutationFn: createRoom,
    onSuccess: options?.onSuccess,
  })
}
