export const VIDEO_REFERENCE_EXTENSIONS = new Set(['mp4', 'mov'])

export const AUDIO_REFERENCE_EXTENSIONS = new Set(['wav', 'mp3'])

export function promptMentionItem(type, number, item, source) {
  const label = `${type[0].toUpperCase()}${type.slice(1)}${number}`
  return {
    id: `${source}-${number}-${item?.cupsyAssetId || item?.uid || item?.name || label}`,
    type,
    label,
    token: `[${label}]`,
    name: item?.name || item?.file?.name || label,
    preview: type === 'image' ? item?.preview : null,
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
