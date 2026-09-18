import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Dialog, Field, P } from '@/primitives'
import { HStack, VStack } from '@/styled-system/jsx'
import { createPortal } from 'react-dom'

type CopyMeetingInfoDialogProps = {
  isOpen: boolean
  onOpenChange: (isOpen: boolean) => void
  onCopy: (subject: string) => Promise<void>
}

export const CopyMeetingInfoDialog = ({
  isOpen,
  onOpenChange,
  onCopy,
}: CopyMeetingInfoDialogProps) => {
  const { t } = useTranslation('rooms', {
    keyPrefix: 'copyMeetingInfoDialog',
  })
  const [subject, setSubject] = useState('')

  useEffect(() => {
    if (isOpen) setSubject('')
  }, [isOpen])

  return createPortal(
    <Dialog
      title={t('title')}
      isOpen={isOpen}
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
          label={t('subjectLabel')}
          value={subject}
          onChange={setSubject}
          autoFocus
        />
        <HStack justifyContent="end">
          <Button variant="secondary" onPress={() => onOpenChange(false)}>
            {t('cancel')}
          </Button>
          <Button
            variant="primary"
            onPress={async () => {
              await onCopy(subject.trim())
              onOpenChange(false)
            }}
          >
            {t('copy')}
          </Button>
        </HStack>
      </VStack>
    </Dialog>,
    document.body
  )
}
