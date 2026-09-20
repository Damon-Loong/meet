import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Dialog, Field, P, Text } from '@/primitives'
import { HStack, VStack } from '@/styled-system/jsx'
import { ApiError } from '@/api/ApiError'

const localDateTime = (date: Date) => {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

export type MeetingCreationMode = 'instant' | 'later'

type CreateMeetingDialogProps = {
  mode: MeetingCreationMode | null
  isPending: boolean
  onOpenChange: (isOpen: boolean) => void
  onCreate: (values: {
    topic: string
    start?: string
    end?: string
    inviteEmails: string[]
  }) => Promise<void>
}

export const CreateMeetingDialog = ({
  mode,
  isPending,
  onOpenChange,
  onCreate,
}: CreateMeetingDialogProps) => {
  const { t } = useTranslation('home', { keyPrefix: 'createMeetingDialog' })
  const [topic, setTopic] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [emails, setEmails] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (mode) {
      setTopic('')
      setStart('')
      setEnd('')
      setEmails('')
      setError('')
    }
  }, [mode])

  return (
    <Dialog
      title={t(mode === 'later' ? 'laterTitle' : 'instantTitle')}
      isOpen={mode !== null}
      onOpenChange={onOpenChange}
      role="dialog"
      type="flex"
    >
      <VStack
        alignItems="stretch"
        gap="1rem"
        width="min(28rem, calc(100vw - 4rem))"
      >
        <P>{t('description')}</P>
        <Field
          type="text"
          label={t('topicLabel')}
          value={topic}
          onChange={setTopic}
          isRequired
          autoFocus
        />
        {mode === 'later' && (
          <>
            <label>
              <Text>开始时间 *</Text>
              <input
                type="datetime-local"
                value={start}
                min={localDateTime(new Date())}
                onChange={(event) => setStart(event.target.value)}
                required
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  border: '1px solid #777',
                  borderRadius: '4px',
                }}
              />
            </label>
            <label>
              <Text>结束时间 *</Text>
              <input
                type="datetime-local"
                value={end}
                min={start}
                onChange={(event) => setEnd(event.target.value)}
                required
                style={{
                  width: '100%',
                  padding: '0.75rem',
                  border: '1px solid #777',
                  borderRadius: '4px',
                }}
              />
            </label>
            <Field
              type="text"
              label="邀请人邮箱（选填）"
              description="多个邮箱请使用逗号、分号或换行分隔。"
              value={emails}
              onChange={setEmails}
            />
          </>
        )}
        {error && (
          <p role="alert" style={{ color: '#b42318' }}>
            {error}
          </p>
        )}
        <HStack justifyContent="end">
          <Button
            variant="secondary"
            onPress={() => onOpenChange(false)}
            isDisabled={isPending}
          >
            {t('cancel')}
          </Button>
          <Button
            variant="primary"
            isDisabled={
              !topic.trim() ||
              isPending ||
              (mode === 'later' && (!start || !end || end <= start))
            }
            onPress={async () => {
              setError('')
              if (mode === 'later' && new Date(start).getTime() <= Date.now()) {
                setError(
                  '开始时间必须晚于当前时间，请重新选择。时间按本机时区填写。'
                )
                return
              }
              try {
                await onCreate({
                  topic: topic.trim(),
                  start: start ? new Date(start).toISOString() : undefined,
                  end: end ? new Date(end).toISOString() : undefined,
                  inviteEmails: emails
                    .split(/[\s,;，；]+/)
                    .map((email) => email.trim().toLowerCase())
                    .filter(
                      (email, index, values) =>
                        Boolean(email) && values.indexOf(email) === index
                    ),
                })
              } catch (cause) {
                const body = cause instanceof ApiError ? cause.body : undefined
                if (
                  body &&
                  typeof body === 'object' &&
                  'scheduled_start' in body
                ) {
                  setError('开始时间必须晚于当前时间，请重新选择。')
                } else if (
                  body &&
                  typeof body === 'object' &&
                  'scheduled_end' in body
                ) {
                  setError('结束时间必须晚于开始时间。')
                } else if (
                  body &&
                  typeof body === 'object' &&
                  'invite_emails' in body
                ) {
                  setError('邀请人邮箱格式有误，请检查后重试。')
                } else {
                  setError('创建会议失败，请检查输入或稍后重试。')
                }
              }
            }}
          >
            {isPending
              ? t('creating')
              : t(mode === 'later' ? 'createLater' : 'startNow')}
          </Button>
        </HStack>
      </VStack>
    </Dialog>
  )
}
