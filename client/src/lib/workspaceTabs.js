import { SEEDANCE_20, CUPSY_AUDIO_MODEL } from './generationSettings.js'

export function makeImgTab(id) {
  return {
    id, prompt: '', aspectRatio: '1:1', resolution: '1K',
    customWidth: 1024, customHeight: 1024, customAspectLocked: false, customAspectRatio: 1,
    uploadedImages: [], outputFormat: 'png', background: 'default', watermark: false,
    loading: false, taskId: null, dbTaskId: null, taskStatus: null, generatedImages: [], error: null, errorType: null, errorDetails: null,
  }
}

export function makeVideoTab(id) {
  return {
    id, prompt: '', model: SEEDANCE_20, ratio: 'adaptive', duration: 5, resolution: '720p', outputFormat: 'mp4',
    fast: false, audio: true, returnLastFrame: false, mode: 'keyframe',
    firstFrame: null, lastFrame: null, refImages: [], refVideos: [], refAudios: [],
    loading: false, videoUrl: null, lastFrameUrl: null, progress: 0, eta: 0, error: null,
    taskId: null, dbTaskId: null, taskProvider: null, taskStatus: null,
  }
}

export const DEFAULT_AUDIO_FORM = {
  prompt: '', model: CUPSY_AUDIO_MODEL, outputFormat: 'mp3', sampleRate: 44100,
  enableSubtitle: true, watermark: false, referenceMode: 'none', speaker: '', references: [],
}

export function selectPersistedImageTabs(tabs) {
  return (tabs || []).map(({
    loading, taskStatus, taskId, dbTaskId, generatedImages,
    error, errorType, errorDetails, ...tab
  }) => ({
    ...tab,
    uploadedImages: (tab.uploadedImages || []).map(({ uploadError, ...image }) => image),
  }))
}

export function hydrateImageTabs(savedTabs, _currentTabs = []) {
  const sourceTabs = savedTabs?.length ? savedTabs : [makeImgTab(1)]
  return sourceTabs.map(saved => {
    return {
      ...makeImgTab(saved.id),
      ...saved,
      loading: false,
      taskId: null,
      dbTaskId: null,
      taskStatus: null,
      generatedImages: [],
      error: null,
      errorType: null,
      errorDetails: null,
    }
  })
}

export function selectPersistedVideoTabs(tabs) {
  return (tabs || []).map(({
    loading, taskStatus, taskId, dbTaskId, taskProvider, progress, eta,
    videoUrl, lastFrameUrl, error, ...tab
  }) => ({
    ...tab,
    refVideos: (tab.refVideos || [])
      .filter(video => video.url && !video.uploading)
      .map(({ progress: _progress, uploading: _uploading, ...video }) => video),
  }))
}

export function hydrateVideoTabs(savedTabs, currentTabs = []) {
  const runtime = new Map((currentTabs || []).map(tab => [Number(tab.id), tab]))
  const sourceTabs = savedTabs?.length ? savedTabs : [makeVideoTab(1)]
  return sourceTabs.map(saved => {
    const current = runtime.get(Number(saved.id))
    const persistedVideos = saved.refVideos || []
    const persistedIds = new Set(persistedVideos.map(video => video.uid))
    const uploadingVideos = (current?.refVideos || []).filter(video => video.uploading && !persistedIds.has(video.uid))
    return {
      ...makeVideoTab(saved.id),
      ...saved,
      refVideos: [...persistedVideos, ...uploadingVideos],
      loading: false,
      taskId: null,
      dbTaskId: null,
      taskProvider: null,
      taskStatus: null,
      progress: 0,
      eta: 0,
      videoUrl: null,
      lastFrameUrl: null,
      error: null,
    }
  })
}

export function mergeNormalizedImageTabs(currentTabs, normalizedTabs) {
  return currentTabs.map(tab => {
    const normalized = normalizedTabs.find(saved => saved.id === tab.id)
    if (!normalized) return tab
    return {
      ...tab,
      uploadedImages: (tab.uploadedImages || []).map((image, index) => {
        const saved = image.uid
          ? normalized.uploadedImages?.find(item => item.uid === image.uid)
          : normalized.uploadedImages?.[index]
        return saved ? { ...image, ...saved, uploadError: false } : image
      }),
    }
  })
}

export function mergeNormalizedVideoTabs(currentTabs, normalizedTabs) {
  return hydrateVideoTabs(normalizedTabs, currentTabs)
}

export const IMAGE_WORKSPACE_OPTIONS = {
  selectPersisted: selectPersistedImageTabs,
  hydrate: hydrateImageTabs,
  mergeNormalized: mergeNormalizedImageTabs,
}

export const VIDEO_WORKSPACE_OPTIONS = {
  selectPersisted: selectPersistedVideoTabs,
  hydrate: hydrateVideoTabs,
  mergeNormalized: mergeNormalizedVideoTabs,
}
