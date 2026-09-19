import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Dialog, Field, P, Text } from '@/primitives'
import { HStack, VStack } from '@/styled-system/jsx'

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

  useEffect(() => {
    if (mode) {
      setTopic('')
      setStart('')
      setEnd('')
      setEmails('')
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
                min={new Date().toISOString().slice(0, 16)}
                onChange={(event) => setStart(event.target.value)}
                required
                style={{ width: '100%', padding: '0.75rem', border: '1px solid #777', borderRadius: '4px' }}
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
                style={{ width: '100%', padding: '0.75rem', border: '1px solid #777', borderRadius: '4px' }}
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
            onPress={() =>
              onCreate({
                topic: topic.trim(),
                start: start ? new Date(start).toISOString() : undefined,
                end: end ? new Date(end).toISOString() : undefined,
                inviteEmails: emails
                  .split(/[\s,;，；]+/)
                  .map((email) => email.trim().toLowerCase())
                  .filter((email, index, values) =>
                    Boolean(email) && values.indexOf(email) === index
                  ),
              })
            }
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
