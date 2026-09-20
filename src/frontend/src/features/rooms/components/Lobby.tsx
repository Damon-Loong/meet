import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useSnapshot } from 'valtio'
import { css } from '@/styled-system/css'
import { VStack } from '@/styled-system/jsx'
import { H } from '@/primitives/H'
import { Field } from '@/primitives/Field'
import { Form, Text } from '@/primitives'
import { Spinner } from '@/primitives/Spinner'
import { keys } from '@/api/queryKeys'
import { queryClient } from '@/api/queryClient'
import { useLoginHint } from '@/hooks/useLoginHint'
import { useUser } from '@/features/auth/api/useUser'
import { saveEmail, saveUsername, userStore } from '@/stores/user'
import { fetchRoom } from '../api/fetchRoom'
import { ApiAccessLevel } from '../api/ApiRoom'
import { ApiLobbyStatus, type ApiRequestEntry } from '../api/requestEntry'
import { useLobby } from '../hooks/useLobby'

export const Lobby = ({
  roomId,
  enterRoom,
}: {
  roomId: string
  enterRoom: () => void
}) => {
  const { t } = useTranslation('rooms', { keyPrefix: 'join' })

  const { user } = useUser()
  const { username, email } = useSnapshot(userStore)

  // Room data strategy:
  // 1. Initial fetch is performed to check access and get LiveKit configuration
  // 2. Data remains valid for 6 hours to avoid unnecessary refetches
  // 3. State is manually updated via queryClient when a waiting participant is accepted
  // 4. No automatic refetching or revalidation occurs during this period
  const {
    data: roomData,
    error,
    isError,
    refetch: refetchRoom,
  } = useQuery({
    queryKey: [keys.room, roomId],
    queryFn: () =>
      fetchRoom({
        roomId,
        username: username || user?.full_name,
        email: email || user?.email,
      }),
    staleTime: 0,
    retry: false,
    enabled: true,
  })

  useEffect(() => {
    if (isError && error?.statusCode == 404) {
      // The room component will handle the room creation if the user is authenticated
      enterRoom()
    }
  }, [isError, error, enterRoom])

  const handleAccepted = (response: ApiRequestEntry) => {
    queryClient.setQueryData([keys.room, roomId], {
      ...roomData,
      livekit: response.livekit,
    })
    enterRoom()
  }

  const { status, startWaiting } = useLobby({
    roomId,
    username: username || user?.full_name || 'anonymous',
    email: email || user?.email || '',
    onAccepted: handleAccepted,
  })

  const { openLoginHint } = useLoginHint()

  const handleSubmit = async () => {
    const { data } = await refetchRoom()

    if (data?.is_expired) return

    if (!data?.livekit) {
      // Display a message to inform the user that by logging in, they won't have to wait for room entry approval.
      if (data?.access_level == ApiAccessLevel.TRUSTED) {
        openLoginHint()
      }
      startWaiting()
      return
    }

    enterRoom()
  }

  if (roomData?.is_expired) {
    return (
      <VStack alignItems="center" textAlign="center">
        <H lvl={1} margin={false} centered>
          {roomData.lifecycle_status === 'cancelled'
            ? '会议已取消'
            : '会议链接已失效'}
        </H>
        <Text as="p" variant="note">
          请联系主持人创建新会议并获取新的邀请链接。
        </Text>
      </VStack>
    )
  }

  switch (status) {
    case ApiLobbyStatus.TIMEOUT:
      return (
        <VStack alignItems="center" textAlign="center">
          <H lvl={1} margin={false} centered>
            {t('timeoutInvite.title')}
          </H>
          <Text as="p" variant="note">
            {t('timeoutInvite.body')}
          </Text>
        </VStack>
      )

    case ApiLobbyStatus.DENIED:
      return (
        <VStack alignItems="center" textAlign="center">
          <H lvl={1} margin={false} centered>
            {t('denied.title')}
          </H>
          <Text as="p" variant="note">
            {t('denied.body')}
          </Text>
        </VStack>
      )

    case ApiLobbyStatus.WAITING:
      return (
        <VStack alignItems="center" textAlign="center">
          <H lvl={1} margin={false} centered>
            {t('waiting.title')}
          </H>
          <Text
            as="p"
            variant="note"
            className={css({ marginBottom: '1.5rem' })}
          >
            {t('waiting.body')}
          </Text>
          <Spinner />
        </VStack>
      )

    default:
      return (
        <Form
          onSubmit={handleSubmit}
          submitLabel={t('joinLabel')}
          submitButtonProps={{
            fullWidth: true,
          }}
        >
          <VStack marginBottom={1}>
            <H lvl={1} margin="sm" centered>
              {t('heading')}
            </H>
            <Field
              type="text"
              onChange={saveUsername}
              label={t('usernameLabel')}
              aria-label={t('usernameLabel')}
              id="input-name"
              defaultValue={username || user?.full_name}
              validate={(value) => !value && t('errors.usernameEmpty')}
              wrapperProps={{ noMargin: true, fullWidth: true }}
              autoComplete="name"
              maxLength={50}
            />
            <Field
              type="text"
              onChange={saveEmail}
              label="邮箱"
              aria-label="邮箱"
              id="input-email"
              defaultValue={email || user?.email}
              validate={(value) => {
                if (!value) return '请输入邮箱'
                if (
                  value.indexOf('@') < 1 ||
                  value.lastIndexOf('.') < value.indexOf('@') + 2
                ) {
                  return '请输入有效的邮箱地址'
                }
              }}
              wrapperProps={{ noMargin: true, fullWidth: true }}
              autoComplete="email"
              maxLength={254}
            />
          </VStack>
        </Form>
      )
  }
}
