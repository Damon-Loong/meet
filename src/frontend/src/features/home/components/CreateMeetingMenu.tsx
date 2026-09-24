import { useTranslation } from 'react-i18next'
import { MenuItem, Menu as RACMenu } from 'react-aria-components'
import { Button, Menu } from '@/primitives'
import { navigateTo } from '@/navigation/navigateTo'
import { generateRoomId, useCreateRoom } from '@/features/rooms'
import { RiAddLine, RiLink } from '@remixicon/react'
import { LaterMeetingDialog } from '@/features/home/components/LaterMeetingDialog'
import { useState } from 'react'

import { menuRecipe } from '@/primitives/menuRecipe'
import { ApiRoom } from '@/features/rooms/api/ApiRoom'
import { useSnapshot } from 'valtio'
import { userStore } from '@/stores/user'
import {
  CreateMeetingDialog,
  type MeetingCreationMode,
} from './CreateMeetingDialog'

export const CreateMeetingMenu = () => {
  const { username } = useSnapshot(userStore)

  const { t } = useTranslation('home')
  const { mutateAsync: createRoom, isPending } = useCreateRoom()
  const [laterRoom, setLaterRoom] = useState<null | ApiRoom>(null)
  const [creationMode, setCreationMode] = useState<MeetingCreationMode | null>(
    null
  )

  const handleCreate = async ({
    topic,
    start,
    end,
    inviteEmails,
    isPermanent,
  }: {
    topic: string
    start?: string
    end?: string
    inviteEmails: string[]
    isPermanent: boolean
  }) => {
    const slug = generateRoomId()
    const data = await createRoom({
      slug,
      topic,
      username,
      roomType: creationMode === 'later' ? 'scheduled' : 'instant',
      isPermanent: creationMode === 'instant' && isPermanent,
      scheduledStart: start,
      scheduledEnd: end,
      inviteEmails,
    })
    setCreationMode(null)

    if (creationMode === 'instant') {
      // Use the normal join flow so browser media permissions are initialized
      // only after the participant submits their name and email.
      navigateTo('room', data.slug)
      return
    }

    setLaterRoom(data)
  }

  return (
    <>
      <Menu>
        <Button variant="primary" data-attr="create-meeting">
          {t('createMeeting')}
        </Button>
        <RACMenu>
          <MenuItem
            className={menuRecipe({ icon: true, variant: 'light' }).item}
            onAction={() => setCreationMode('instant')}
            data-attr="create-option-instant"
          >
            <RiAddLine size={18} />
            {t('createMenu.instantOption')}
          </MenuItem>
          <MenuItem
            className={menuRecipe({ icon: true, variant: 'light' }).item}
            onAction={() => setCreationMode('later')}
            data-attr="create-option-later"
          >
            <RiLink size={18} />
            {t('createMenu.laterOption')}
          </MenuItem>
        </RACMenu>
      </Menu>
      <CreateMeetingDialog
        mode={creationMode}
        isPending={isPending}
        onOpenChange={(isOpen) => {
          if (!isOpen) setCreationMode(null)
        }}
        onCreate={handleCreate}
      />
      <LaterMeetingDialog
        room={laterRoom}
        onOpenChange={() => setLaterRoom(null)}
      />
    </>
  )
}
