// LIBRARY-GLOBAL-20261116 S4a: one global library; “生成历史” is a locked system folder, not a source.
export const librarySources={local:'本地素材库'}
// Older callers may still pass saved/uploaded/local: all open 全部素材. 'generated' opens the “生成历史”
// folder; 'characters' opens the global character library view (browse mode only).
export const normalizeLibrarySource=source=>source==='generated'||source==='characters'?source:'local'
