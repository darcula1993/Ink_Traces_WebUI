export const librarySources={generated:'生成历史',local:'本地素材'}
// Older callers can still request saved/uploaded; both now enter the local union.
export const normalizeLibrarySource=source=>source==='generated'?'generated':'local'
