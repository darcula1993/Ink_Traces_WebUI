export const VIDEO_REFERENCE_EXTENSIONS = new Set(['mp4', 'mov'])

export const AUDIO_REFERENCE_EXTENSIONS = new Set(['wav', 'mp3'])

export const LIBRARY_MEDIA_URL_PATTERN = /^\/api\/canvas\/media\/([0-9a-f]{32})$/

export function isDirectImageReferenceUrl(url) {
  if (typeof url !== 'string' || !url) return false
  return url.startsWith('/api/workspace/assets/img_tabs/') || LIBRARY_MEDIA_URL_PATTERN.test(url)
}

export function libraryItemToImageReference(item, makeUid = () => `library-${Date.now()}-${Math.random()}`) {
  const asset = item?.asset
  if (asset?.kind && asset.kind !== 'image') return null
  const url = typeof asset?.url === 'string' ? asset.url : ''
  const match = LIBRARY_MEDIA_URL_PATTERN.exec(url)
  if (!match) return null
  const width = Number(asset.width)
  const height = Number(asset.height)
  const size = Number(asset.size_bytes ?? asset.size)
  return {
    uid: makeUid(),
    mediaId: item?.media_id || asset.id || match[1],
    file: null,
    preview: url,
    thumbnail: item?.thumbnail_url || asset.thumbnail_url || `${url}/thumbnail`,
    name: asset.name || 'image.png',
    ...(Number.isFinite(width) && width > 0 ? { width } : {}),
    ...(Number.isFinite(height) && height > 0 ? { height } : {}),
    ...(Number.isFinite(size) && size > 0 ? { size } : {}),
    hasAlpha: typeof asset.has_alpha === 'boolean' ? asset.has_alpha : null,
  }
}

export function isLibraryMediaUrl(url) {
  return typeof url === 'string' && LIBRARY_MEDIA_URL_PATTERN.test(url)
}

export function libraryItemToVideoImageReference(item, makeUid = () => `library-${Date.now()}-${Math.random()}`) {
  const ref = libraryItemToImageReference(item, makeUid)
  if (!ref) return null
  const { hasAlpha: _hasAlpha, ...rest } = ref
  return rest
}

export function libraryItemToVideoReference(item, makeUid = () => `library-vid-${Date.now()}-${Math.random()}`) {
  const asset = item?.asset
  const url = typeof asset?.url === 'string' ? asset.url : ''
  const match = LIBRARY_MEDIA_URL_PATTERN.exec(url)
  if (!match || asset.kind !== 'video') return null
  const duration = Number(asset.duration_seconds ?? asset.duration)
  return {
    uid: makeUid(),
    mediaId: item?.media_id || asset.id || match[1],
    name: asset.name || 'video.mp4',
    url,
    thumbnail: item?.thumbnail_url || asset.thumbnail_url || `${url}/thumbnail`,
    ...(Number.isFinite(duration) && duration > 0 ? { duration } : {}),
    progress: 100,
    uploading: false,
  }
}

export function libraryItemToVideoAudioReference(item, makeUid = () => `library-aud-${Date.now()}-${Math.random()}`) {
  const asset = item?.asset
  const url = typeof asset?.url === 'string' ? asset.url : ''
  const match = LIBRARY_MEDIA_URL_PATTERN.exec(url)
  if (!match || asset.kind !== 'audio') return null
  const duration = Number(asset.duration_seconds ?? asset.duration)
  return {
    uid: makeUid(),
    mediaId: item?.media_id || asset.id || match[1],
    file: null,
    preview: url,
    url,
    name: asset.name || 'audio.wav',
    ...(Number.isFinite(duration) && duration > 0 ? { duration } : {}),
  }
}

export function libraryItemToAudioToolReference(item, makeUid = () => `library-tool-aud-${Date.now()}-${Math.random()}`) {
  const asset = item?.asset
  const url = typeof asset?.url === 'string' ? asset.url : ''
  const match = LIBRARY_MEDIA_URL_PATTERN.exec(url)
  if (!match || !['image', 'audio'].includes(asset.kind)) return null
  return {
    uid: makeUid(),
    mediaId: item?.media_id || asset.id || match[1],
    cupsyAssetId: null,
    kind: asset.kind,
    name: asset.name || (asset.kind === 'image' ? 'image.png' : 'audio.wav'),
    preview: url,
    thumbnail: asset.kind === 'image' ? (item?.thumbnail_url || asset.thumbnail_url || `${url}/thumbnail`) : null,
    status: 'local',
  }
}

export function buildAudioReferencePayload(references = []) {
  const list = Array.isArray(references) ? references : []
  const hasLibraryDirect = list.some(ref => !ref?.cupsyAssetId && isLibraryMediaUrl(ref?.preview || ref?.url))
  if (!hasLibraryDirect) {
    return { cupsy_assets: list.map(reference => ({ id: reference.cupsyAssetId })) }
  }
  return {
    cupsy_assets: [],
    reference_media_urls: list.map(ref => (
      ref?.cupsyAssetId ? `cupsy:${ref.cupsyAssetId}` : (ref?.preview || ref?.url)
    )),
  }
}

export function buildVideoGenerateSubmission(tab, commonFields) {
  const readyRefVideos = (tab.refVideos || []).filter(video => video.url && !video.uploading)
  const cupsyAssets = tab.mode === 'keyframe'
    ? [
        tab.firstFrame?.cupsyAssetId && { id: tab.firstFrame.cupsyAssetId, role: 'first_frame' },
        tab.lastFrame?.cupsyAssetId && { id: tab.lastFrame.cupsyAssetId, role: 'last_frame' },
      ].filter(Boolean)
    : [
        ...(tab.refImages || []).filter(item => item.cupsyAssetId).map(item => ({ id: item.cupsyAssetId, role: 'reference_image' })),
        ...readyRefVideos.filter(item => item.cupsyAssetId).map(item => ({ id: item.cupsyAssetId, role: 'reference_video' })),
        ...(tab.refAudios || []).filter(item => item.cupsyAssetId).map(item => ({ id: item.cupsyAssetId, role: 'reference_audio' })),
      ]

  const videoUrls = readyRefVideos.filter(v => !v.cupsyAssetId).map(v => v.url)
  const uploadsToAppend = [] // ordered list of { field, file?, url?, name }
  const extraFields = {}

  if (tab.mode === 'keyframe') {
    for (const [slot, fileField, urlField, fallbackName] of [
      [tab.firstFrame, 'image', 'first_frame_url', 'first_frame.png'],
      [tab.lastFrame, 'last_image', 'last_frame_url', 'last_frame.png'],
    ]) {
      if (!slot || slot.cupsyAssetId) continue
      if (slot.file) {
        uploadsToAppend.push({ field: fileField, file: slot.file, name: slot.name || slot.file.name || fallbackName })
      } else if (isLibraryMediaUrl(slot.preview)) {
        extraFields[urlField] = slot.preview
      } else if (slot.preview) {
        uploadsToAppend.push({ field: fileField, url: slot.preview, name: slot.name || fallbackName })
      }
    }
  } else {
    const planOrderedList = (items, fileField, urlsField, fallbackPrefix, fallbackExt) => {
      const nonCupsy = (items || []).filter(item => !item.cupsyAssetId)
      if (!nonCupsy.length) return
      const hasAnyLibrary = nonCupsy.some(item => !item.file && isLibraryMediaUrl(item.preview || item.url))
      if (!hasAnyLibrary) {
        nonCupsy.forEach((item, index) => {
          const fallbackName = item.name || item.file?.name || `${fallbackPrefix}_${index}.${fallbackExt}`
          if (item.file) uploadsToAppend.push({ field: fileField, file: item.file, name: fallbackName })
          else if (item.preview) uploadsToAppend.push({ field: fileField, url: item.preview, name: fallbackName })
        })
        return
      }
      const orderedUrls = []
      let uploadIndex = 0
      nonCupsy.forEach((item, index) => {
        const refUrl = item.preview || item.url
        if (!item.file && isLibraryMediaUrl(refUrl)) {
          orderedUrls.push(refUrl)
        } else {
          const fallbackName = item.name || item.file?.name || `${fallbackPrefix}_${index}.${fallbackExt}`
          if (item.file) uploadsToAppend.push({ field: fileField, file: item.file, name: fallbackName })
          else if (item.preview) uploadsToAppend.push({ field: fileField, url: item.preview, name: fallbackName })
          else return
          orderedUrls.push(`upload:${uploadIndex++}`)
        }
      })
      if (orderedUrls.length) extraFields[urlsField] = orderedUrls
    }
    planOrderedList(tab.refImages, 'ref_images', 'ref_image_urls', 'ref', 'png')
    planOrderedList(tab.refAudios, 'ref_audios', 'ref_audio_urls', 'audio', 'wav')
  }

  if (uploadsToAppend.length === 0) {
    return {
      mode: 'json',
      body: {
        ...commonFields,
        ...(videoUrls.length ? { ref_video_urls: videoUrls } : {}),
        ...(cupsyAssets.length ? { cupsy_assets: cupsyAssets } : {}),
        ...extraFields,
      },
    }
  }
  return {
    mode: 'multipart',
    fields: {
      ...commonFields,
      ...(videoUrls.length ? { ref_video_urls: videoUrls } : {}),
      ...(cupsyAssets.length ? { cupsy_assets: cupsyAssets } : {}),
      ...extraFields,
    },
    uploadsToAppend,
  }
}

// V140 #15 (user 2026-11-14): references are written like the sd25-pe skill:
// @图片N / @视频N / @音频N, numbered per kind in reference order. The old
// [ImageN] form is no longer recognized (plain text); nothing is migrated.
export const REFERENCE_KIND_LABELS = Object.freeze({ image: '图片', video: '视频', audio: '音频' })
const ENGLISH_KIND = Object.freeze({ image: 'Image', video: 'Video', audio: 'Audio' })
export const REFERENCE_TOKEN_SOURCE = '@(图片|视频|音频)([1-9]\\d*)'
// Greedy digits: "@图片12" is reference 12, never "@图片1" followed by "2".
export const referenceTokenPattern = new RegExp(REFERENCE_TOKEN_SOURCE, 'g')
export function referenceTokenRanges(text) {
  const ranges = [], pattern = new RegExp(REFERENCE_TOKEN_SOURCE, 'g'), value = String(text || '')
  for (let match = pattern.exec(value); match; match = pattern.exec(value)) ranges.push({ start: match.index, end: match.index + match[0].length, token: match[0] })
  return ranges
}
// V140 #16: Backspace right after / Delete right before a whole reference removes it
// in one keystroke. Returns the range to select (the browser then deletes it
// natively, so the textarea's own undo keeps working), or null for default behavior.
export function referenceDeletionRange(text, selectionStart, selectionEnd, key) {
  if (selectionStart !== selectionEnd || !['Backspace', 'Delete'].includes(key)) return null
  return referenceTokenRanges(text).find(range => key === 'Backspace' ? range.end === selectionStart : range.start === selectionStart) || null
}

export function promptMentionItem(type, number, item, source) {
  const label = `${REFERENCE_KIND_LABELS[type] || type}${number}`
  return {
    id: `${source}-${number}-${item?.cupsyAssetId || item?.uid || item?.name || label}`,
    type,
    label,
    alias: `${ENGLISH_KIND[type] || type}${number}`,
    token: `@${label}`,
    name: item?.name || item?.file?.name || label,
    preview: type === 'image' ? (item?.thumbnail || item?.preview || null) : null,
    thumbnail: type === 'video' ? item?.thumbnail : null,
  }
}

export function currentPromptMentionItems(appMode, imageTab, videoTab, audioForm) {
  if (appMode === 'image') {
    return (imageTab.uploadedImages || []).map((item, index) => (
      promptMentionItem('image', index + 1, item, 'image-form')
    ))
  }

  if (appMode === 'video') {
    if (videoTab.mode === 'keyframe') {
      return [
        videoTab.firstFrame && promptMentionItem('image', 1, videoTab.firstFrame, 'first-frame'),
        videoTab.lastFrame && promptMentionItem('image', 2, videoTab.lastFrame, 'last-frame'),
      ].filter(Boolean)
    }
    return [
      ...(videoTab.refImages || []).map((item, index) => promptMentionItem('image', index + 1, item, 'video-image')),
      ...(videoTab.refVideos || [])
        .filter(item => item.url && !item.uploading)
        .map((item, index) => promptMentionItem('video', index + 1, item, 'video-video')),
      ...(videoTab.refAudios || []).map((item, index) => promptMentionItem('audio', index + 1, item, 'video-audio')),
    ]
  }

  if (appMode === 'audio') {
    const references = audioForm.references || []
    const imageReferences = references.filter(item => item.kind === 'image')
    const audioReferences = references.filter(item => item.kind === 'audio')
    const audioOffset = audioForm.speaker ? 1 : 0
    return [
      ...imageReferences.map((item, index) => promptMentionItem('image', index + 1, item, 'audio-image')),
      ...audioReferences.map((item, index) => promptMentionItem('audio', index + audioOffset + 1, item, 'audio-audio')),
    ]
  }

  return []
}

export function restoredTaskReferences(task) {
  const result = task.result || {}
  const params = task.params || {}
  const refs = Array.isArray(result.local_refs) ? result.local_refs : []
  const types = Array.isArray(result.local_ref_types) ? result.local_ref_types : []
  const roles = Array.isArray(result.local_ref_roles) ? result.local_ref_roles : []
  const names = Array.isArray(result.local_ref_names) ? result.local_ref_names : []
  const assetIds = Array.isArray(result.local_ref_asset_ids) ? result.local_ref_asset_ids : []
  const typeCounts = { image: 0, video: 0, audio: 0 }

  return refs.map((url, index) => {
    const type = ['image', 'video', 'audio'].includes(types[index]) ? types[index] : 'image'
    const typeIndex = typeCounts[type]++
    let role = roles[index]
    if (!role) {
      role = task.type === 'video' && params.video_mode === 'keyframe' && type === 'image'
        ? typeIndex === 0 ? 'first_frame' : 'last_frame'
        : `reference_${type}`
    }
    const idFromUrl = String(url).match(/\/api\/cupsy\/assets\/(\d+)\/content/)?.[1]
    const parsedAssetId = Number(assetIds[index] ?? idFromUrl)
    return {
      url,
      type,
      role,
      name: names[index] || `reference_${type}_${typeIndex + 1}`,
      cupsyAssetId: Number.isInteger(parsedAssetId) && parsedAssetId > 0 ? parsedAssetId : null,
    }
  })
}

export function fileExtension(file) {
  return String(file?.name || '').split('.').pop()?.toLowerCase() || ''
}

export function isImageFile(file) {
  return Boolean(file && String(file.type || '').startsWith('image/'))
}

export function isVideoFile(file) {
  return Boolean(file && (
    ['video/mp4', 'video/quicktime'].includes(String(file.type || '').toLowerCase()) ||
    VIDEO_REFERENCE_EXTENSIONS.has(fileExtension(file))
  ))
}

export function isAudioFile(file) {
  return Boolean(file && (
    ['audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/mp3'].includes(String(file.type || '').toLowerCase()) ||
    AUDIO_REFERENCE_EXTENSIONS.has(fileExtension(file))
  ))
}

export function readFileDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = event => resolve(event.target.result)
    reader.onerror = () => reject(reader.error || new Error('文件读取失败'))
    reader.readAsDataURL(file)
  })
}

export function hasExternalFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes('Files')
}

export function videoDropZoneHandlers(onFiles) {
  return {
    onDragEnter: event => {
      if (!hasExternalFiles(event)) return
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.dataset.dragging = 'true'
    },
    onDragOver: event => {
      if (!hasExternalFiles(event)) return
      event.preventDefault()
      event.stopPropagation()
      event.dataTransfer.dropEffect = 'copy'
    },
    onDragLeave: event => {
      if (!hasExternalFiles(event) || event.currentTarget.contains(event.relatedTarget)) return
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.dataset.dragging = 'false'
    },
    onDrop: event => {
      if (!hasExternalFiles(event)) return
      event.preventDefault()
      event.stopPropagation()
      event.currentTarget.dataset.dragging = 'false'
      onFiles(Array.from(event.dataTransfer?.files || []))
    },
  }
}
