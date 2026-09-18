import { useMutation, UseMutationOptions } from '@tanstack/react-query'
import { fetchApi } from '@/api/fetchApi'
import type { ApiError } from '@/api/ApiError'
import type { ApiRoom } from '@/features/rooms/api/ApiRoom'
import { RecordingMode } from '../types'

export interface StopRecordingParams {
  id: string
  mode: RecordingMode
}

const stopRecording = ({ id, mode }: StopRecordingParams): Promise<ApiRoom> => {
  return fetchApi(`rooms/${id}/stop-recording/`, {
    method: 'POST',
    body: JSON.stringify({ mode }),
  })
}

export function useStopRecording(
  options?: UseMutationOptions<ApiRoom, ApiError, StopRecordingParams>
) {
  return useMutation<ApiRoom, ApiError, StopRecordingParams>({
    mutationFn: stopRecording,
    onSuccess: options?.onSuccess,
    onError: options?.onError,
  })
}
