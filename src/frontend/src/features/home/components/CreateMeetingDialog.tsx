import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Dialog, Field, P } from '@/primitives'
import { HStack, VStack } from '@/styled-system/jsx'

export type MeetingCreationMode = 'instant' | 'later'

type CreateMeetingDialogProps = {
  mode: MeetingCreationMode | null
  isPending: boolean
  onOpenChange: (isOpen: boolean) => void
  onCreate: (topic: string) => Promise<void>
}

export const CreateMeetingDialog = ({
  mode,
  isPending,
  onOpenChange,
  onCreate,
}: CreateMeetingDialogProps) => {
  const { t } = useTranslation('home', { keyPrefix: 'createMeetingDialog' })
  const [topic, setTopic] = useState('')

  useEffect(() => {
    if (mode) setTopic('')
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
            isDisabled={!topic.trim() || isPending}
            onPress={() => onCreate(topic.trim())}
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
