import { useEffect, useState } from 'react'
import { Button, P, Text } from '@/primitives'
import { VStack } from '@/styled-system/jsx'
import { fetchApi } from '@/api/fetchApi'
import { navigateTo } from '@/navigation/navigateTo'

type Confirmation = {
  confirmed: boolean
  topic: string
  starts_at: string
  ends_at: string
  timezone: string
}

const MeetingConfirmation = () => {
  const [result, setResult] = useState<Confirmation | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get('token')
    if (!token) {
      setError('确认链接无效。')
      return
    }
    fetchApi<Confirmation>(`rooms/confirm-invitation/${encodeURIComponent(token)}/`, {
      method: 'POST',
    })
      .then(setResult)
      .catch(() => setError('确认链接无效，或会议已被取消。'))
  }, [])

  return (
    <VStack alignItems="center" justifyContent="center" minHeight="100vh" gap="1rem" padding="2rem">
      {error ? (
        <>
          <Text as="h1" variant="h1">无法确认参会</Text>
          <P>{error}</P>
        </>
      ) : result ? (
        <>
          <Text as="h1" variant="h1">已确认参会</Text>
          <P>您已确认参加“{result.topic}”。系统将不再发送会前提醒。</P>
          <P>
            开始时间：{new Date(result.starts_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
          </P>
          <P>确认参会不会立即进入会议，请在会议开始时使用邀请邮件中的链接。</P>
          <Button variant="primary" onPress={() => navigateTo('home')}>返回首页</Button>
        </>
      ) : (
        <P>正在确认参会……</P>
      )}
    </VStack>
  )
}

export default MeetingConfirmation
