// CHARACTER-LIBRARY-20261114 C (spec revision, user 11-14): choosing a character in the @ menu writes it
// into the prompt as visible, editable text. Its reference images (and, for video/audio nodes, its voice
// audio) are imported as ordinary node references appended at the end; the leading 【人物】 block gets the
// character's lines (sd25-pe style) whose @图片N / @音频N are real, bound references; the plain name is
// inserted at the caret. Nothing is expanded at submit time. node.characterRefs ({characterId: {name,
// assetIds, updatedAt?}}; assetIds = the imported canvas asset ids, updatedAt = the character's
// updated_at at insert/sync time) only drives the "角色已更新 / 已删除" notices and the user-triggered sync.
import {canvasMentionItems,bindReferenceMentions,referenceTokenPattern} from './canvasReferences.js'
import {referenceDropError} from './canvasReferenceDrop.js'
import {imageCapabilities} from './imageGenerationRules.js'

export const CHARACTER_BLOCK_TITLE = '【人物】'
export const CHARACTER_EXCHANGE_LINE = '各人物的外貌、服装和声音不互相交换。'
const COUNT = ['零', '一', '两', '三', '四', '五', '六', '七', '八', '九', '十']
const PLACEHOLDER = /\u0000(\d+)\u0000/g
const CARET = '\u0001'

const cleanDescription = value => String(value || '').replace(/\s*[\r\n]+\s*/g, ' ').trim()
const hasVoice = character => character?.voice?.type === 'audio' && Boolean(character.voice.asset_id)

// What a node type takes from a character: image nodes images only, audio nodes the voice only,
// video nodes both. Description is written for image and video nodes.
export function characterUsage(nodeType, character) {
  const images = nodeType === 'audio' ? [] : (character?.images || []).filter(image => image?.asset_id)
  const voice = nodeType !== 'image' && hasVoice(character)
  const description = nodeType === 'audio' ? '' : cleanDescription(character?.description)
  return { images, voice, description }
}

const characterRef = (character, added) => ({ name: character.name, assetIds: [...new Set(added.map(asset => asset.id))], ...(typeof character.updated_at === 'string' && character.updated_at ? { updatedAt: character.updated_at } : {}) })

// Lines of one character (imageTokens / audioToken are the tokens or placeholders to write).
export function characterLines(name, { imageTokens = [], audioToken = null, description = '' } = {}) {
  const lines = []
  if (imageTokens.length === 1) lines.push(`${name}对应${imageTokens[0]}，只采用五官、发型和服装，不采用图片背景。`)
  else if (imageTokens.length > 1) lines.push(`${name}对应${imageTokens.join('、')}，只采用五官、发型和服装，不采用图片背景；${COUNT[imageTokens.length] || imageTokens.length}张参考共同定义同一人物，不生成多个副本。`)
  if (description) lines.push(`${name}的外貌设定：${description}`)
  if (audioToken) lines.push(`${audioToken}用于${name}的音色和台词。`)
  return lines
}

// The block is the prompt's leading 【人物】 line plus the following lines up to the first empty line.
export function splitCharacterBlock(text) {
  const value = String(text || '')
  if (value !== CHARACTER_BLOCK_TITLE && !value.startsWith(`${CHARACTER_BLOCK_TITLE}\n`)) return { hasBlock: false, lines: [], body: value }
  const rows = value.split('\n'), end = rows.indexOf('', 1)
  return { hasBlock: true, lines: rows.slice(1, end < 0 ? undefined : end), body: end < 0 ? '' : rows.slice(end + 1).join('\n') }
}

const REF = '(?:@(?:图片|视频|音频)[1-9]\\d*|\\u0000\\d+\\u0000)'
const OWNER_PATTERNS = [new RegExp(`^(.+?)对应${REF}`), /^(.+?)的外貌设定：/, new RegExp(`^${REF}用于(.+?)的音色和台词。$`)]
export function characterLineOwner(line) {
  for (const pattern of OWNER_PATTERNS) { const match = String(line).match(pattern); if (match) return match[1] }
  return null
}
export const blockCharacterNames = text => [...new Set(splitCharacterBlock(text).lines.map(characterLineOwner).filter(Boolean))]
export const hasCharacterInBlock = (text, name) => blockCharacterNames(text).includes(name)

// Replace (or add) one character's lines; the "不互相交换" sentence is kept once, last, when ≥2 characters.
export function writeCharacterLines(text, name, lines, removeName = name) {
  const { hasBlock, lines: current, body } = splitCharacterBlock(text)
  const kept = current.filter(line => line !== CHARACTER_EXCHANGE_LINE && characterLineOwner(line) !== removeName && characterLineOwner(line) !== name)
  const next = [...kept, ...lines]
  if (!next.length) return hasBlock ? body : String(text || '')
  if (new Set(next.map(characterLineOwner).filter(Boolean)).size >= 2) next.push(CHARACTER_EXCHANGE_LINE)
  return `${CHARACTER_BLOCK_TITLE}\n${next.join('\n')}\n\n${body}`
}

function addLimitError(node, assets, kinds, provider) {
  const issue = referenceDropError(node, assets, kinds, provider)
  if (issue) return issue
  if (node.type === 'image') {
    const max = imageCapabilities(provider?.provider || provider?.id, provider?.capability_model || provider?.model).maxReferences
    if (assets.filter(asset => asset.kind === 'image').length + kinds.length > max) return `图像节点最多 ${max} 张参考图，当前已有 ${assets.filter(asset => asset.kind === 'image').length} 张`
  }
  return null
}

// What to import for a character, or why it cannot be inserted (nothing is imported then).
export function planCharacterInsert({ node, assets = [], provider = null, character }) {
  const usage = characterUsage(node.type, character), name = character.name
  if (node.type === 'audio' && !usage.voice) return { error: `角色“${name}”没有参考音频，音频节点只使用角色声音` }
  if (!usage.images.length && !usage.voice && !usage.description) return { error: `角色“${name}”没有可用于该节点的参考图或描述` }
  const kinds = [...usage.images.map(() => 'image'), ...(usage.voice ? ['audio'] : [])]
  const limit = kinds.length ? addLimitError(node, assets, kinds, provider) : null
  if (limit) return { error: `角色“${name}”需要 ${usage.images.length ? `${usage.images.length} 张参考图` : ''}${usage.images.length && usage.voice ? '和 ' : ''}${usage.voice ? '1 段参考音频' : ''}，超出参考上限：${limit}` }
  return { error: null, imageIds: usage.images.map(image => image.asset_id), voice: usage.voice }
}

const dedupe = items => [...new Map(items.filter(Boolean).map(item => [item.id, item])).values()]

// Shared rewrite for insert and sync. Every bound token of node.text becomes a placeholder, the block is
// rewritten, then placeholders become the tokens of the next reference list (so renumbering is exact).
function rewriteCharacter({ node, assets, character, imported, removeIds = new Set(), removeName, caret }) {
  const usage = characterUsage(node.type, character)
  const added = [...(imported.assets || []), ...(usage.voice && imported.voice ? [imported.voice] : [])]
  if ((imported.assets || []).length !== usage.images.length || (usage.voice && !imported.voice)) throw new Error('角色素材导入结果不完整，未插入；请重试')
  const bindings = bindReferenceMentions(node, assets, node.text)
  const marks = []
  const mark = (id, original) => { marks.push({ id, original }); return `\u0000${marks.length - 1}\u0000` }
  let text = caret ? `${(node.text || '').slice(0, caret.start)}${character.name}${CARET}${(node.text || '').slice(caret.end)}` : (node.text || '')
  text = text.replace(referenceTokenPattern, token => bindings[token] ? mark(bindings[token], token) : token)
  const referenceAssets = dedupe([...(node.referenceAssets || []).filter(asset => !removeIds.has(asset.id)), ...added])
  const order = node.referenceOrder?.length ? { referenceOrder: [...new Set([...node.referenceOrder.filter(id => !removeIds.has(id)), ...added.map(asset => asset.id)])] } : {}
  const next = { ...node, referenceAssets, ...order }
  const nextAssets = dedupe([...assets.filter(asset => !removeIds.has(asset.id)), ...added])
  const tokenById = new Map(canvasMentionItems(next, nextAssets).map(item => [item.assetId, item.token]))
  const lines = characterLines(character.name, {
    imageTokens: (imported.assets || []).map(asset => mark(asset.id)),
    audioToken: usage.voice ? mark(imported.voice.id) : null,
    description: usage.description,
  })
  text = writeCharacterLines(text, character.name, lines, removeName)
  const mentions = {}
  const missing = []
  text = text.replace(PLACEHOLDER, (_, index) => {
    const { id, original } = marks[Number(index)], token = tokenById.get(id)
    if (token) { mentions[token] = id; return token }
    if (original) { mentions[original] = id; return original } // a stale binding stays stale
    missing.push(id); return ''
  })
  if (missing.length) throw new Error('当前参考模式无法为角色素材编号（首尾帧模式只使用两张图片），未插入')
  const cursor = text.indexOf(CARET)
  if (cursor >= 0) text = text.slice(0, cursor) + text.slice(cursor + 1)
  return {
    patch: { text, referenceAssets, ...order, referenceMentions: mentions, characterRefs: { ...(node.characterRefs || {}), [character.id]: characterRef(character, added) } },
    cursor,
    assets: nextAssets,
  }
}

// After the import: the block lines, references and bindings for one inserted character.
// caret = {start, end} of the "@query" typed in the textarea (replaced by the plain name).
export function applyCharacterInsert({ node, assets = [], character, imported, caret }) {
  if (hasCharacterInBlock(node.text, character.name)) {
    const text = `${(node.text || '').slice(0, caret.start)}${character.name}${(node.text || '').slice(caret.end)}`
    return { patch: { text }, cursor: caret.start + character.name.length }
  }
  return rewriteCharacter({ node, assets, character, imported, caret, removeName: character.name })
}

// User-triggered sync: replace the character's block lines and the references they used (a reference
// still mentioned elsewhere in the prompt is kept). Plain-text names elsewhere are left untouched.
export function applyCharacterSync({ node, assets = [], character, imported }) {
  const ref = node.characterRefs?.[character.id]
  const oldName = ref?.name || character.name
  const bindings = bindReferenceMentions(node, assets, node.text)
  const { lines, body } = splitCharacterBlock(node.text)
  const owned = lines.filter(line => characterLineOwner(line) === oldName)
  const others = [...lines.filter(line => characterLineOwner(line) !== oldName), body].join('\n')
  const tokensIn = value => [...new Set(String(value).match(referenceTokenPattern) || [])]
  const keep = new Set(tokensIn(others).map(token => bindings[token]).filter(Boolean))
  const newIds = new Set([...(imported.assets || []), imported.voice].filter(Boolean).map(asset => asset.id))
  const previous = [...tokensIn(owned.join('\n')).map(token => bindings[token]), ...(ref?.assetIds || [])]
  const removeIds = new Set(previous.filter(id => id && !keep.has(id) && !newIds.has(id)))
  const result = rewriteCharacter({ node, assets, character, imported, removeIds, removeName: oldName })
  return { patch: result.patch, assets: result.assets }
}

// Limit check for a whole reference list (used after a sync, whose old references are replaced).
export const referenceLimitError = (node, assets, provider) => addLimitError(node, [], assets.map(asset => asset.kind), provider)

// Notices for characters still written in the block: deleted from the library, or changed since the
// insert/sync (updated_at differs from the recorded updatedAt, or the name differs). characters=null: unknown.
export function characterNotices(node, characters) {
  const present = new Set(blockCharacterNames(node.text)), notices = []
  const byId = characters ? new Map(characters.map(character => [character.id, character])) : null
  for (const [id, ref] of Object.entries(node.characterRefs || {})) {
    if (!present.has(ref.name) || !byId) continue
    const character = byId.get(id)
    if (!character) { notices.push({ id, name: ref.name, status: 'deleted', text: `角色“${ref.name}”已从角色库删除；提示词与已导入的参考保留，仍按普通参考使用` }); continue }
    const renamed = character.name !== ref.name, changed = Boolean(ref.updatedAt) && character.updated_at !== ref.updatedAt
    if (renamed || changed) notices.push({ id, name: ref.name, status: 'updated', text: `角色“${ref.name}”已更新${renamed ? `（名称改为“${character.name}”）` : ''}，可同步` })
  }
  return notices
}

// @ menu entries for the character library (shown after the node's own references).
export function characterMentionItems(characters = []) {
  return characters.map(character => ({
    id: `character-${character.id}`, type: 'character', characterId: character.id,
    label: character.name, alias: '', token: character.name, name: character.description || '角色',
    preview: character.images?.[0]?.thumbnail_url || character.images?.[0]?.url || null,
  }))
}
