import { type ApiRoom } from './ApiRoom'
import { fetchApi } from '@/api/fetchApi'

export const fetchRoom = ({
  roomId,
  username,
  email,
}: {
  roomId: string
  username?: string
  email?: string
}) => {
  const params = new URLSearchParams()
  if (username) params.set('username', username)
  if (email) params.set('email', email)
  const query = params.size ? `?${params.toString()}` : ''

  return fetchApi<ApiRoom>(`/rooms/${roomId}/${query}`)
}
