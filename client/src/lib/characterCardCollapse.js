// V24-W2-CHAR-CARD-20261121: lossless split/join for the leading 【人物】/【物件】 character prompt block.
// Used by CanvasNodePrompt to fold the leading character definitions into a compact badge by default
// while keeping the underlying prompt text byte-for-byte identical for the generation provider.
import { CHARACTER_EXCHANGE_LINE } from './canvasCharacters.js'

const HEADER_RE = /^(【(?:人物|物件)】)(\r?\n)/
const REF_TOKEN = '@(?:图片|视频|音频)[1-9]\\d*'
const LINE_OWNER_PATTERNS = [
  new RegExp(`^(.+?)对应${REF_TOKEN}`),
  /^(.+?)的外[貌观]设定：/,
  new RegExp(`^${REF_TOKEN}用于(.+?)的(?:音色和台词|声音效果)。$`),
]

function parseOwner(line) {
  for (const pattern of LINE_OWNER_PATTERNS) {
    const match = String(line).match(pattern)
    if (match && match[1]) return match[1]
  }
  return null
}

/**
 * Split a prompt into its leading character block and editable story body.
 *
 * Returns `{ block, names, body }` where:
 * - `block`: the exact leading substring (including trailing blank-line separator when present),
 *   or `''` when the prompt does not start with a valid character card block.
 * - `names`: deduplicated character/prop names in order of appearance.
 * - `body`: the remaining prompt text after `block`.
 *
 * Invariant: for every string `text`,
 *   `joinCharacterPromptBlock(res.block, res.body) === String(text || '')`
 * holds byte-for-byte.
 */
export function splitCharacterPromptBlock(text) {
  const value = String(text ?? '')
  const header = HEADER_RE.exec(value)
  if (!header) return { block: '', names: [], body: value }

  let pos = header[0].length
  const names = []
  const seen = new Set()
  let lineCount = 0
  let blockEnd = -1

  while (pos <= value.length) {
    if (pos === value.length) {
      blockEnd = pos
      break
    }
    const lf = value.indexOf('\n', pos)
    const hasLf = lf >= 0
    const rawLineEnd = hasLf ? lf : value.length
    const lineText = hasLf && lf > pos && value[lf - 1] === '\r'
      ? value.slice(pos, lf - 1)
      : value.slice(pos, rawLineEnd)
    const nextPos = hasLf ? lf + 1 : value.length

    if (lineText === '') {
      // Blank line terminates the block and belongs to `block` so round-trip is exact.
      blockEnd = nextPos
      break
    }

    if (lineText === CHARACTER_EXCHANGE_LINE) {
      lineCount += 1
      pos = nextPos
      continue
    }

    const owner = parseOwner(lineText)
    if (!owner) {
      return { block: '', names: [], body: value }
    }
    lineCount += 1
    if (!seen.has(owner)) {
      seen.add(owner)
      names.push(owner)
    }
    pos = nextPos
  }

  if (!lineCount || !names.length || blockEnd < 0) {
    return { block: '', names: [], body: value }
  }

  return {
    block: value.slice(0, blockEnd),
    names,
    body: value.slice(blockEnd),
  }
}

/**
 * Re-join a previously split `block` with an edited `body`.
 * Keeps `block` byte-for-byte intact whenever it already ends with its blank-line separator
 * (or when `body` is empty). Only inserts a separator if `block` had no trailing blank line
 * and the user subsequently typed a non-empty `body`.
 */
export function joinCharacterPromptBlock(block, body) {
  const safeBlock = String(block ?? '')
  const safeBody = String(body ?? '')
  if (!safeBlock) return safeBody
  if (safeBody === '') return safeBlock
  if (/(?:\r\n\r\n|\n\n)$/.test(safeBlock)) return safeBlock + safeBody
  const eol = safeBlock.includes('\r\n') ? '\r\n' : '\n'
  if (safeBlock.endsWith(eol)) return `${safeBlock}${eol}${safeBody}`
  return `${safeBlock}${eol}${eol}${safeBody}`
}

/**
 * Compact 1-line badge label for collapsed character blocks:
 * `['林默']` -> `'@林默'`, `['林默', '青铜灯笼']` -> `'@林默 +1'`.
 */
export function formatCharacterBadgeLabel(names = []) {
  if (!Array.isArray(names) || !names.length) return ''
  return names.length === 1 ? `@${names[0]}` : `@${names[0]} +${names.length - 1}`
}
