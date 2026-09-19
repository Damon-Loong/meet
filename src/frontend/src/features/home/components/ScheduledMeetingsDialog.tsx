import { useQuery } from '@tanstack/react-query'
import { Button, Dialog, H, P } from '@/primitives'
import { VStack, HStack } from '@/styled-system/jsx'
import { fetchApi } from '@/api/fetchApi'
import type { ApiRoom } from '@/features/rooms/api/ApiRoom'
import { getRouteUrl } from '@/navigation/getRouteUrl'

type RoomPage = { results: ApiRoom[] }

export const ScheduledMeetingsDialog = () => {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['scheduled-meetings'],
    queryFn: () => fetchApi<RoomPage>('rooms/'),
  })
  const meetings = (data?.results ?? []).filter(
    (room) => room.room_type === 'scheduled' && room.lifecycle_status === 'active'
  )

  return (
    <Dialog title="我的日程会议">
      <VStack alignItems="stretch" gap="1rem" width="min(36rem, calc(100vw - 4rem))">
        {isLoading ? (
          <P>正在加载……</P>
        ) : meetings.length === 0 ? (
          <P>暂无未结束的日程会议。</P>
        ) : (
          meetings.map((room) => (
            <VStack
              key={room.id}
              alignItems="stretch"
              gap="0.5rem"
              padding="1rem"
              border="1px solid #ddd"
              borderRadius="0.5rem"
            >
              <H lvl={3}>{room.topic}</H>
              {room.scheduled_start && room.scheduled_end && (
                <P>
                  {new Date(room.scheduled_start).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
                  {' 至 '}
                  {new Date(room.scheduled_end).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
                </P>
              )}
              <HStack gap="0.5rem">
                <Button variant="secondary" size="sm" onPress={() => navigator.clipboard.writeText(getRouteUrl('room', room.slug))}>
                  复制链接
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onPress={async () => {
                    if (!window.confirm('确定取消该会议吗？取消后会议链接将立即失效。')) return
                    await fetchApi(`rooms/${room.id}/cancel-scheduled/`, { method: 'POST' })
                    await refetch()
                  }}
                >
                  取消会议
                </Button>
              </HStack>
            </VStack>
          ))
        )}
      </VStack>
    </Dialog>
  )
}
