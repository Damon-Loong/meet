export const roomIdPattern = '[a-z]{3}-[a-z]{4}-[a-z]{3}'

// Case-insensitive and with optional hyphens
export const flexibleRoomIdPattern =
  '(?:[a-zA-Z0-9]{3}-?[a-zA-Z0-9]{4}-?[a-zA-Z0-9]{3}|(?=[a-z0-9-]{3,50}$)[a-z0-9]+(?:-[a-z0-9]+)*)'

const legacyRoomRegex = new RegExp(`^${roomIdPattern}$`)
const customRoomRegex = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

export const isRoomValid = (roomIdOrUrl: string) => {
  const roomId = roomIdOrUrl.startsWith(`${window.location.origin}/`)
    ? roomIdOrUrl.slice(window.location.origin.length + 1)
    : roomIdOrUrl
  return (
    legacyRoomRegex.test(roomId) ||
    (roomId.length >= 3 &&
      roomId.length <= 50 &&
      customRoomRegex.test(roomId) &&
      !/^[a-z0-9]{10}$/.test(roomId))
  )
}

export const normalizeRoomId = (roomId: string) => {
  const cleanId = roomId.toLowerCase().replace(/-/g, '')
  if (cleanId.length === 10) {
    return `${cleanId.slice(0, 3)}-${cleanId.slice(3, 7)}-${cleanId.slice(7, 10)}`
  }
  return roomId
}
