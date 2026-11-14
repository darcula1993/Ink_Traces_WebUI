export const librarySources={generated:'生成历史',local:'本地素材'}
// Older callers can still request saved/uploaded; both now enter the local union.
// 'characters' opens the global character library view (browse mode only).
export const normalizeLibrarySource=source=>source==='generated'||source==='characters'?source:'local'
