import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, ArchiveRestore, Check, CheckCheck, ChevronRight, Columns3, Download, Filter, FolderHeart, FolderPlus, Heart, Image as ImageIcon, LoaderCircle, LayoutGrid, ListChecks, Pencil, RefreshCw, Search, SortDesc, Trash2, X } from 'lucide-react'
import IconButton from './ui/IconButton'
import { useWorkspaceState } from '../lib/useWorkspaceState'
import { ACTIVE_STATUSES, TASK_PAGE_SIZE, STATUS_BATCH_SIZE, STATUS_POLL_DELAY, sameValue, mergeTaskStatus, DEFAULT_GALLERY_PREFERENCES, CARD_SIZE_OPTIONS, CARD_DETAIL_OPTIONS, SORT_OPTIONS, DEFAULT_TASK_FILTERS, STATUS_FILTER_OPTIONS, DATE_FILTER_OPTIONS, GROUP_COLORS, EMPTY_NAVIGATION, providerLabel, createdAfterForRange, serverItem, taskTypeLabel, needsRetryConfirmation } from './gallery/taskModel.js'
import { TaskTypeIcon } from './gallery/TaskPreview.jsx'
import { TaskCardList } from './gallery/TaskCards.jsx'
import { TaskCompareModal, TaskDetailModal } from './gallery/TaskModals.jsx'
import ConfirmDialog from './ui/ConfirmDialog'

function useLiveCallback(callback) {
  const ref = useRef(callback)
  ref.current = callback
  return useCallback((...args) => ref.current(...args), [])
}

function TaskGallery({
  mode,
  refreshToken,
  onReuseTask,
}) {
  const [tasks, setTasks] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [view, setView] = useState('all')
  const [favoriteGroup, setFavoriteGroup] = useState('all')
  const [favoriteGroups, setFavoriteGroups] = useState([])
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [filters, setFilters] = useState(DEFAULT_TASK_FILTERS)
  const [filterOptions, setFilterOptions] = useState({ providers: [], models: [] })
  const [filterMenuOpen, setFilterMenuOpen] = useState(false)
  const [selectedKey, setSelectedKey] = useState(null)
  const [selectedOverride, setSelectedOverride] = useState(null)
  const [selectionMode, setSelectionMode] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState(() => new Set())
  const [selectionUniverse, setSelectionUniverse] = useState(() => new Set())
  const [selectingAll, setSelectingAll] = useState(false)
  const [navigation, setNavigation] = useState(EMPTY_NAVIGATION)
  const [navigationLoading, setNavigationLoading] = useState(false)
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false)
  const [groupMenuOpen, setGroupMenuOpen] = useState(false)
  const [bulkGroupMenuOpen, setBulkGroupMenuOpen] = useState(false)
  const [bulkDownloadMenuOpen, setBulkDownloadMenuOpen] = useState(false)
  const [compareItems, setCompareItems] = useState([])
  const [compareLoading, setCompareLoading] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupColor, setNewGroupColor] = useState('green')
  const [editingGroupId, setEditingGroupId] = useState(null)
  const [editingGroupName, setEditingGroupName] = useState('')
  const [galleryPreferences, setGalleryPreferences] = useWorkspaceState(
    'gallery_preferences',
    DEFAULT_GALLERY_PREFERENCES,
  )
  const layoutMenuRef = useRef(null)
  const filterMenuRef = useRef(null)
  const groupMenuRef = useRef(null)
  const bulkGroupMenuRef = useRef(null)
  const bulkDownloadMenuRef = useRef(null)
  const fetchSequenceRef = useRef(0)
  const listRequestRef = useRef(null)
  const statusRequestRef = useRef(null)
  const detailRequestRef = useRef({ controller: null, sequence: 0 })
  const tasksRef = useRef(tasks)
  tasksRef.current = tasks
  const selectedItemRef = useRef(null)
  selectedItemRef.current = selectedKey ? selectedOverride : null
  const itemCacheRef = useRef(new WeakMap())
  const navigationRequestRef = useRef({ controller: null, sequence: 0 })
  const handledRefreshTokenRef = useRef(refreshToken)
  const cardSize = CARD_SIZE_OPTIONS.some(option => option.value === galleryPreferences?.cardSize)
    ? galleryPreferences.cardSize
    : DEFAULT_GALLERY_PREFERENCES.cardSize
  const cardDetails = CARD_DETAIL_OPTIONS.some(option => option.value === galleryPreferences?.cardDetails)
    ? galleryPreferences.cardDetails
    : DEFAULT_GALLERY_PREFERENCES.cardDetails
  const cardSort = SORT_OPTIONS.some(option => option.value === galleryPreferences?.sort)
    ? galleryPreferences.sort
    : DEFAULT_GALLERY_PREFERENCES.sort
  const createdAfter = useMemo(() => createdAfterForRange(filters.dateRange), [filters.dateRange])
  const activeFilters = useMemo(() => [
    filters.status && {
      key: 'status',
      label: STATUS_FILTER_OPTIONS.find(option => option.value === filters.status)?.label || filters.status,
    },
    filters.provider && { key: 'provider', label: providerLabel(filters.provider) },
    filters.model && { key: 'model', label: filters.model },
    filters.dateRange && {
      key: 'dateRange',
      label: DATE_FILTER_OPTIONS.find(option => option.value === filters.dateRange)?.label || filters.dateRange,
    },
  ].filter(Boolean), [filters])

  useEffect(() => {
    if (!layoutMenuOpen && !filterMenuOpen) return undefined
    const closeMenu = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return
      if (event.type === 'pointerdown' && (
        layoutMenuRef.current?.contains(event.target) || filterMenuRef.current?.contains(event.target)
      )) return
      setLayoutMenuOpen(false)
      setFilterMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeMenu)
    document.addEventListener('keydown', closeMenu)
    return () => {
      document.removeEventListener('pointerdown', closeMenu)
      document.removeEventListener('keydown', closeMenu)
    }
  }, [filterMenuOpen, layoutMenuOpen])

  useEffect(() => {
    if (!groupMenuOpen && !bulkGroupMenuOpen && !bulkDownloadMenuOpen) return undefined
    const closeMenus = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return
      if (event.type === 'pointerdown' && (
        groupMenuRef.current?.contains(event.target) ||
        bulkGroupMenuRef.current?.contains(event.target) ||
        bulkDownloadMenuRef.current?.contains(event.target)
      )) return
      setGroupMenuOpen(false)
      setBulkGroupMenuOpen(false)
      setBulkDownloadMenuOpen(false)
      setEditingGroupId(null)
    }
    document.addEventListener('pointerdown', closeMenus)
    document.addEventListener('keydown', closeMenus)
    return () => {
      document.removeEventListener('pointerdown', closeMenus)
      document.removeEventListener('keydown', closeMenus)
    }
  }, [bulkDownloadMenuOpen, bulkGroupMenuOpen, groupMenuOpen])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 280)
    return () => window.clearTimeout(timer)
  }, [query])

  const updateGalleryPreference = useCallback((key, value) => {
    setGalleryPreferences(previous => ({
      ...DEFAULT_GALLERY_PREFERENCES,
      ...(previous || {}),
      [key]: value,
    }))
  }, [setGalleryPreferences])

  const buildFilterParams = useCallback((search = debouncedQuery) => ({
    type: mode,
    sort: cardSort,
    ...(view === 'favorite' ? { favorite: true } : {}),
    ...(view === 'active' ? { active: true } : {}),
    ...(view === 'trash' ? { deleted: true } : {}),
    ...(view === 'favorite' && favoriteGroup === 'ungrouped' ? { ungrouped: true } : {}),
    ...(view === 'favorite' && Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0
      ? { favorite_group: Number(favoriteGroup) }
      : {}),
    ...(search ? { q: search } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.provider ? { provider: filters.provider } : {}),
    ...(filters.model ? { model: filters.model } : {}),
    ...(createdAfter ? { created_after: createdAfter } : {}),
  }), [cardSort, createdAfter, debouncedQuery, favoriteGroup, filters, mode, view])

  const buildSelectionParams = useCallback((search = query.trim()) => ({
    type: mode,
    view,
    sort: cardSort,
    ...(view === 'favorite' && favoriteGroup === 'ungrouped' ? { ungrouped: true } : {}),
    ...(view === 'favorite' && Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0
      ? { favorite_group: Number(favoriteGroup) }
      : {}),
    ...(search ? { q: search } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.provider ? { provider: filters.provider } : {}),
    ...(filters.model ? { model: filters.model } : {}),
    ...(createdAfter ? { created_after: createdAfter } : {}),
  }), [cardSort, createdAfter, favoriteGroup, filters, mode, query, view])

  const clearFilters = useCallback(() => setFilters(DEFAULT_TASK_FILTERS), [])
  const clearSearchAndFilters = useCallback(() => {
    setQuery('')
    setDebouncedQuery('')
    setFilters(DEFAULT_TASK_FILTERS)
  }, [])

  const fetchFilterOptions = useCallback(async () => {
    try {
      const response = await axios.get('/api/tasks/filter-options', {
        params: { type: mode, ...(view === 'trash' ? { deleted: true } : {}) },
      })
      if (response.data.success) {
        setFilterOptions({
          providers: response.data.providers || [],
          models: response.data.models || [],
        })
      }
    } catch (requestError) {
      console.warn('Task filter options unavailable', requestError.message)
    }
  }, [mode, view])

  const fetchFavoriteGroups = useCallback(async () => {
    try {
      const response = await axios.get('/api/favorite-groups', { params: { type: mode } })
      if (response.data.success) setFavoriteGroups(response.data.groups || [])
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组加载失败')
    }
  }, [mode])

  useEffect(() => {
    fetchFavoriteGroups()
  }, [fetchFavoriteGroups])

  useEffect(() => {
    fetchFilterOptions()
  }, [fetchFilterOptions])

  const fetchTasks = useCallback(async ({ append = false, offset = 0, preserveLoaded = false } = {}) => {
    const sequence = ++fetchSequenceRef.current
    listRequestRef.current?.abort()
    statusRequestRef.current?.abort()
    const controller = new AbortController()
    listRequestRef.current = controller
    if (!preserveLoaded) setLoading(true)
    try {
      const targetCount = preserveLoaded ? Math.max(TASK_PAGE_SIZE, tasksRef.current.length) : TASK_PAGE_SIZE
      const fetched = []
      let fetchedTotal = 0
      do {
        const response = await axios.get('/api/tasks', {
          params: { ...buildFilterParams(), limit: TASK_PAGE_SIZE, offset: offset + fetched.length },
          signal: controller.signal,
        })
        if (sequence !== fetchSequenceRef.current || !response.data.success) return
        const page = response.data.tasks || []
        fetched.push(...page)
        fetchedTotal = Number(response.data.total) || 0
        if (page.length < TASK_PAGE_SIZE || offset + fetched.length >= fetchedTotal) break
      } while (fetched.length < targetCount)
      if (!controller.signal.aborted) {
        setTasks(previous => {
          const known = new Set(previous.map(task => Number(task.id)))
          const previousById = new Map(previous.map(task => [Number(task.id), task]))
          const next = append
            ? [...previous, ...fetched.filter(task => !known.has(Number(task.id)))]
            : fetched.map(task => {
              const existing = previousById.get(Number(task.id))
              return sameValue(existing, task) ? existing : task
            })
          return next.length === previous.length && next.every((task, index) => task === previous[index])
            ? previous : next
        })
        setTotal(fetchedTotal)
        setError('')
      }
    } catch (requestError) {
      if (!controller.signal.aborted && sequence === fetchSequenceRef.current) {
        setError(requestError.response?.data?.error || '任务列表加载失败')
      }
    } finally {
      if (listRequestRef.current === controller) listRequestRef.current = null
      if (sequence === fetchSequenceRef.current) setLoading(false)
    }
  }, [buildFilterParams])

  useEffect(() => {
    setTasks([])
    setTotal(0)
    fetchTasks()
  }, [fetchTasks])
  useEffect(() => {
    if (handledRefreshTokenRef.current === refreshToken) return
    handledRefreshTokenRef.current = refreshToken
    fetchTasks({ preserveLoaded: true })
  }, [fetchTasks, refreshToken])
  const items = useMemo(() => tasks.map(task => {
    const cache = itemCacheRef.current
    if (!cache.has(task)) cache.set(task, serverItem(task))
    return cache.get(task)
  }), [tasks])

  const categoryItems = useMemo(() => items.filter(item => {
    if (view === 'favorite' && !item.favorite) return false
    if (view === 'active' && !ACTIVE_STATUSES.has(item.status)) return false
    if (filters.status && item.status !== filters.status) return false
    if (view === 'favorite' && favoriteGroup === 'ungrouped' && item.favoriteGroups?.length) return false
    if (view === 'favorite' && Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0 &&
      !item.favoriteGroups?.some(group => Number(group.id) === Number(favoriteGroup))) return false
    return true
  }), [favoriteGroup, filters.status, items, view])

  // Search is server-side: a matching prompt may extend beyond the summary preview.
  const visibleItems = categoryItems

  const categoryTotal = total
  const selectedTaskCount = [...selectedKeys].filter(token => token.startsWith('task-')).length
  const activeFavoriteGroup = favoriteGroups.find(group => Number(group.id) === Number(favoriteGroup))
  const favoriteGroupLabel = favoriteGroup === 'ungrouped'
    ? '未分组'
    : (activeFavoriteGroup?.name || '全部收藏')
  const allCategorySelected = selectionUniverse.size > 0 &&
    [...selectionUniverse].every(token => selectedKeys.has(token))

  const selectedItem = selectedKey ? selectedOverride : null
  const selectedPosition = Math.max(0, Number(navigation.position || 1) - 1)
  const selectedTotal = Math.max(
    Number(navigation.total || 0),
    selectedItem ? 1 : 0,
  )

  useEffect(() => {
    detailRequestRef.current.controller?.abort()
    detailRequestRef.current.sequence += 1
    setSelectedKey(null)
    setSelectedOverride(null)
    setNavigation(EMPTY_NAVIGATION)
  }, [cardSort, debouncedQuery, favoriteGroup, filters, mode, view])

  const loadNavigation = useCallback(async taskId => {
    navigationRequestRef.current.controller?.abort()
    const controller = new AbortController()
    const sequence = navigationRequestRef.current.sequence + 1
    navigationRequestRef.current = { controller, sequence }
    setNavigationLoading(true)
    setNavigation(EMPTY_NAVIGATION)
    const path = taskId ? `/api/tasks/${taskId}/navigation` : '/api/tasks/navigation'
    let requestError = null

    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await axios.get(path, {
          params: buildSelectionParams(),
          signal: controller.signal,
        })
        if (navigationRequestRef.current.sequence !== sequence) return
        if (response.data.success) {
          setNavigation({ ...EMPTY_NAVIGATION, ...(response.data.navigation || {}) })
        }
        requestError = null
        break
      } catch (error) {
        if (controller.signal.aborted || axios.isCancel(error) || error.code === 'ERR_CANCELED') return
        requestError = error
        const retryable = !error.response || Number(error.response.status) >= 500
        if (!retryable || attempt === 1) break
        await new Promise(resolve => window.setTimeout(resolve, 180))
        if (controller.signal.aborted || navigationRequestRef.current.sequence !== sequence) return
      }
    }

    if (navigationRequestRef.current.sequence !== sequence) return
    if (requestError?.response) {
      setError(requestError.response.data?.error || '任务导航参数无效')
    } else if (requestError) {
      console.warn('Task navigation temporarily unavailable', requestError.message)
    }
    if (navigationRequestRef.current.sequence === sequence) {
      setNavigationLoading(false)
    }
  }, [buildSelectionParams])

  useEffect(() => {
    if (selectedKey) return
    detailRequestRef.current.controller?.abort()
    detailRequestRef.current.sequence += 1
    navigationRequestRef.current.controller?.abort()
    navigationRequestRef.current = {
      controller: null,
      sequence: navigationRequestRef.current.sequence + 1,
    }
    setNavigationLoading(false)
  }, [selectedKey])

  useEffect(() => () => {
    navigationRequestRef.current.controller?.abort()
    navigationRequestRef.current.sequence += 1
    detailRequestRef.current.controller?.abort()
    detailRequestRef.current.sequence += 1
    listRequestRef.current?.abort()
    fetchSequenceRef.current += 1
  }, [])

  const openItem = useLiveCallback(async (item, refreshNavigation = true) => {
    detailRequestRef.current.controller?.abort()
    const controller = new AbortController()
    const sequence = detailRequestRef.current.sequence + 1
    detailRequestRef.current = { controller, sequence }
    setSelectedKey(item.key)
    setSelectedOverride(previous => previous?.key === item.key ? previous : null)
    if (refreshNavigation) loadNavigation(item.taskId)
    try {
      const response = await axios.get(`/api/tasks/${item.taskId}`, { signal: controller.signal })
      if (response.data.success && detailRequestRef.current.sequence === sequence && !controller.signal.aborted) {
        const full = serverItem(response.data.task)
        setSelectedOverride(full)
      }
    } catch (requestError) {
      if (!controller.signal.aborted) setError(requestError.response?.data?.error || '任务详情加载失败')
    }
  })

  useEffect(() => {
    if (!selectedOverride?.taskId) return
    const summary = tasks.find(task => Number(task.id) === Number(selectedOverride.taskId))
    if (!summary) return
    if (summary.updated_at && selectedOverride.source.updated_at && summary.updated_at < selectedOverride.source.updated_at) return
    const activeDetailChanged = ACTIVE_STATUSES.has(selectedOverride.status) && (
      selectedOverride.status !== summary.status || selectedOverride.source.updated_at !== summary.updated_at
    )
    setSelectedOverride(previous => {
      if (!previous || Number(previous.taskId) !== Number(summary.id)) return previous
      const source = mergeTaskStatus({
        ...previous.source,
        favorite: summary.favorite,
        favorite_groups: summary.favorite_groups,
      }, summary)
      return sameValue(source, previous.source) ? previous : serverItem(source)
    })
    // Only the open task needs full references and metadata while it progresses.
    if (activeDetailChanged) openItem(selectedOverride)
  }, [openItem, tasks])

  useEffect(() => {
    let disposed = false
    let timer
    let controller
    const schedule = () => {
      window.clearTimeout(timer)
      if (!disposed && !document.hidden) timer = window.setTimeout(poll, STATUS_POLL_DELAY)
    }
    const poll = async () => {
      window.clearTimeout(timer)
      if (disposed || document.hidden) return
      if (statusRequestRef.current || listRequestRef.current) {
        schedule()
        return
      }
      const active = tasksRef.current.filter(task => ACTIVE_STATUSES.has(task.status))
      const selectedAtStart = selectedItemRef.current
      if (selectedAtStart && ACTIVE_STATUSES.has(selectedAtStart.status) &&
        !active.some(task => Number(task.id) === Number(selectedAtStart.taskId))) {
        active.push(selectedAtStart.source)
      }
      if (!active.length) {
        schedule()
        return
      }
      controller = new AbortController()
      statusRequestRef.current = controller
      const updates = new Map()
      const missing = new Set()
      try {
        for (let offset = 0; offset < active.length; offset += STATUS_BATCH_SIZE) {
          const response = await axios.get('/api/tasks/status', {
            params: { ids: active.slice(offset, offset + STATUS_BATCH_SIZE).map(task => task.id).join(',') },
            signal: controller.signal,
          })
          if (disposed || controller.signal.aborted || document.hidden) return
          if (!response.data.success) throw new Error('Task status request failed')
          for (const task of response.data.tasks || []) updates.set(Number(task.id), task)
          for (const id of response.data.missing_ids || []) missing.add(Number(id))
        }
        const current = tasksRef.current
        const selected = selectedItemRef.current
        const offPage = selected && !current.some(task => Number(task.id) === Number(selected.taskId))
          ? selected : null
        const observed = offPage ? [...current, offPage.source] : current
        const update = offPage && updates.get(Number(offPage.taskId))
        if (update && !(update.updated_at && offPage.source.updated_at && update.updated_at < offPage.source.updated_at)) {
          setSelectedOverride(previous => {
            if (!previous || Number(previous.taskId) !== Number(update.id)) return previous
            const source = mergeTaskStatus(previous.source, update)
            return source === previous.source ? previous : {
              ...serverItem(source),
              favorite: previous.favorite,
              favoriteGroups: previous.favoriteGroups,
            }
          })
          if (ACTIVE_STATUSES.has(offPage.status) && (
            update.status !== offPage.status || update.updated_at !== offPage.source.updated_at
          )) openItem(offPage, update.status !== offPage.status)
        }
        const terminal = observed.some(task => ACTIVE_STATUSES.has(task.status) &&
          updates.has(Number(task.id)) && !ACTIVE_STATUSES.has(updates.get(Number(task.id)).status))
        const membershipChanged = missing.size > 0 || observed.some(task => {
          const update = updates.get(Number(task.id))
          return update && (
            ('deleted_at' in update && Boolean(update.deleted_at) !== Boolean(task.deleted_at)) ||
            (filters.status && update.status !== task.status)
          )
        })
        setTasks(previous => {
          let changed = false
          const next = previous.filter(task => {
            if (!missing.has(Number(task.id))) return true
            changed = true
            return false
          }).map(task => {
            const update = updates.get(Number(task.id))
            const merged = update ? mergeTaskStatus(task, update) : task
            if (merged !== task) changed = true
            return merged
          })
          return changed ? next : previous
        })
        // Unfiltered totals do not change when an existing task finishes.
        if (membershipChanged || (terminal && (view === 'active' || cardSort === 'updated'))) {
          await fetchTasks({ preserveLoaded: true })
        }
      } catch (requestError) {
        if (!controller.signal.aborted) console.warn('Task statuses temporarily unavailable', requestError.message)
      } finally {
        if (statusRequestRef.current === controller) statusRequestRef.current = null
        schedule()
      }
    }
    const visibilityChanged = () => {
      window.clearTimeout(timer)
      if (document.hidden) controller?.abort()
      else poll()
    }
    schedule()
    document.addEventListener('visibilitychange', visibilityChanged)
    return () => {
      disposed = true
      window.clearTimeout(timer)
      controller?.abort()
      document.removeEventListener('visibilitychange', visibilityChanged)
    }
  }, [cardSort, fetchTasks, filters.status, openItem, view])

  const navigate = useCallback(async direction => {
    if (!selectedItem || selectedTotal <= 1 || navigationLoading) return
    const adjacentId = direction < 0 ? navigation.previous_id : navigation.next_id
    const wrapId = direction < 0 ? navigation.last_id : navigation.first_id
    const taskId = Number(adjacentId || wrapId)
    if (!taskId) return
    openItem({ key: `task-${taskId}`, taskId })
  }, [
    loadNavigation,
    navigation,
    navigationLoading,
    openItem,
    selectedItem,
    selectedTotal,
  ])

  const toggleFavorite = useCallback(async item => {
    if (!item.taskId) return
    const favorite = !item.favorite
    try {
      const response = await axios.patch(`/api/tasks/${item.taskId}/favorite`, { favorite })
      const updatedTask = response.data.task
      setTasks(previous => view === 'favorite' && !favorite
        ? previous.filter(task => Number(task.id) !== Number(item.taskId))
        : previous.map(task => Number(task.id) === Number(item.taskId)
          ? { ...task, favorite, favorite_groups: updatedTask?.favorite_groups || [] }
          : task))
      if (view === 'favorite' && !favorite) setTotal(previous => Math.max(0, previous - 1))
      if (view === 'favorite' && !favorite) {
        setSelectedKey(null)
        setSelectedOverride(null)
      } else {
        setSelectedOverride(previous => previous && Number(previous.taskId) === Number(item.taskId)
          ? { ...previous, favorite, favoriteGroups: updatedTask?.favorite_groups || [] }
          : previous)
      }
      fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏状态更新失败')
    }
  }, [fetchFavoriteGroups, view])

  const createFavoriteGroup = useCallback(async event => {
    event?.preventDefault()
    const name = newGroupName.trim()
    if (!name) return
    try {
      await axios.post('/api/favorite-groups', { name, color: newGroupColor })
      setNewGroupName('')
      await fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组创建失败')
    }
  }, [fetchFavoriteGroups, newGroupColor, newGroupName])

  const saveFavoriteGroup = useCallback(async groupId => {
    const name = editingGroupName.trim()
    if (!name) return
    try {
      await axios.patch(`/api/favorite-groups/${groupId}`, { name })
      setEditingGroupId(null)
      setEditingGroupName('')
      await fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组更新失败')
    }
  }, [editingGroupName, fetchFavoriteGroups])

  const removeFavoriteGroup = useCallback(async group => {
    if (!window.confirm(`删除收藏分组“${group.name}”？任务仍会保留在收藏中。`)) return
    try {
      await axios.delete(`/api/favorite-groups/${group.id}`)
      if (Number(favoriteGroup) === Number(group.id)) setFavoriteGroup('all')
      await fetchFavoriteGroups()
      fetchTasks()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '收藏分组删除失败')
    }
  }, [favoriteGroup, fetchFavoriteGroups, fetchTasks])

  const toggleItemGroup = useCallback(async (item, groupId) => {
    if (!item.taskId) return
    const current = new Set((item.favoriteGroups || []).map(group => Number(group.id)))
    if (current.has(Number(groupId))) current.delete(Number(groupId))
    else current.add(Number(groupId))
    try {
      const response = await axios.patch(`/api/tasks/${item.taskId}/favorite-groups`, {
        group_ids: [...current],
      })
      const updated = response.data.task
      setTasks(previous => previous.map(task => Number(task.id) === Number(item.taskId)
        ? { ...task, favorite: true, favorite_groups: updated.favorite_groups || [] }
        : task))
      setSelectedOverride(previous => previous && Number(previous.taskId) === Number(item.taskId)
        ? { ...previous, favorite: true, favoriteGroups: updated.favorite_groups || [] }
        : previous)
      await fetchFavoriteGroups()
      const updatedGroupIds = new Set((updated.favorite_groups || []).map(group => Number(group.id)))
      const noLongerMatches = view === 'favorite' && (
        (favoriteGroup === 'ungrouped' && updatedGroupIds.size > 0) ||
        (Number.isInteger(Number(favoriteGroup)) && Number(favoriteGroup) > 0 && !updatedGroupIds.has(Number(favoriteGroup)))
      )
      if (noLongerMatches) {
        setSelectedKey(null)
        setSelectedOverride(null)
      }
      fetchTasks()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务收藏分组更新失败')
    }
  }, [favoriteGroup, fetchFavoriteGroups, fetchTasks, view])

  const deleteTask = useCallback(async item => {
    const permanent = view === 'trash'
    const message = permanent
      ? '彻底删除此任务及其输出文件？此操作无法撤销。'
      : '将此任务移到回收站？输出文件会保留，之后可以恢复。'
    if (!window.confirm(message)) return
    try {
      await axios.delete(`/api/tasks/${item.taskId}`, { params: permanent ? { permanent: true } : {} })
      setTasks(previous => previous.filter(task => Number(task.id) !== Number(item.taskId)))
      setTotal(previous => Math.max(0, previous - 1))
      setSelectedKey(null)
      setSelectedOverride(null)
      setNavigation(EMPTY_NAVIGATION)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务删除失败')
    }
  }, [view])

  const cancelTask = useLiveCallback(async item => {
    if (!item.taskId || !window.confirm('取消这个任务？已开始的上游请求可能仍会完成，但结果不会写入本地任务。')) return
    try {
      const response = await axios.post(`/api/tasks/${item.taskId}/cancel`)
      const updated = response.data.task
      setTasks(previous => previous.map(task => Number(task.id) === Number(item.taskId) ? updated : task))
      setSelectedOverride(previous => previous && Number(previous.taskId) === Number(item.taskId)
        ? { ...previous, ...serverItem(updated), key: previous.key }
        : previous)
      if (updated.status !== item.status && (view === 'active' || filters.status)) {
        await fetchTasks({ preserveLoaded: true })
      }
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务取消失败')
    }
  })

  const [retryConfirm, setRetryConfirm] = useState(null)
  const retryTask = useCallback(async (item, confirmed = false) => {
    if (!item.taskId) return
    // A result-unknown task may already have been billed upstream; never
    // resend it without the user's explicit duplicate-billing confirmation.
    if (item.resultUnknown && !confirmed) { setRetryConfirm(item); return }
    try {
      const response = await axios.post(`/api/tasks/${item.taskId}/retry`, confirmed ? { confirm_duplicate_billing: true } : undefined)
      const retried = response.data.task
      setTasks(previous => cardSort === 'oldest'
        ? [...previous.filter(task => Number(task.id) !== Number(retried.id)), retried]
        : [retried, ...previous.filter(task => Number(task.id) !== Number(retried.id))])
      setTotal(previous => previous + 1)
      setSelectedKey(null)
      setSelectedOverride(null)
      setRetryConfirm(null)
      fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      if (!confirmed && needsRetryConfirmation(requestError)) { setRetryConfirm({ ...item, resultUnknown: true }); return }
      if (confirmed) throw requestError
      setError(requestError.response?.data?.error || '任务重试失败')
    }
  }, [cardSort, fetchFavoriteGroups])

  const restoreTask = useCallback(async item => {
    if (!item.taskId) return
    try {
      await axios.post(`/api/tasks/${item.taskId}/restore`)
      setTasks(previous => previous.filter(task => Number(task.id) !== Number(item.taskId)))
      setTotal(previous => Math.max(0, previous - 1))
      setSelectedKey(null)
      setSelectedOverride(null)
      setNavigation(EMPTY_NAVIGATION)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务恢复失败')
    }
  }, [])

  const toggleSelectionMode = useCallback(() => {
    if (selectionMode) {
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      setBulkDownloadMenuOpen(false)
      setSelectionMode(false)
      return
    }
    setSelectedKey(null)
    setSelectedOverride(null)
    setSelectionMode(true)
  }, [selectionMode])

  const toggleSelection = useCallback(key => {
    setSelectedKeys(previous => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(async () => {
    if (allCategorySelected) {
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      return
    }
    setSelectingAll(true)
    try {
      const response = await axios.get('/api/tasks/selection', {
        params: buildSelectionParams(),
      })
      const next = new Set((response.data.ids || []).map(taskId => `task-${taskId}`))
      setSelectionUniverse(new Set(next))
      setSelectedKeys(next)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '全选任务失败')
    } finally {
      setSelectingAll(false)
    }
  }, [allCategorySelected, buildSelectionParams])

  const openSelectedComparison = useCallback(async () => {
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    if (taskIds.length < 2 || taskIds.length > 4) return
    setCompareLoading(true)
    try {
      const responses = await Promise.all(taskIds.map(taskId => axios.get(`/api/tasks/${taskId}`)))
      const compared = responses
        .filter(response => response.data.success)
        .map(response => serverItem(response.data.task))
      if (compared.length >= 2) setCompareItems(compared)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '任务对比加载失败')
    } finally {
      setCompareLoading(false)
    }
  }, [selectedKeys])

  const deleteSelected = useCallback(async () => {
    if (!selectedKeys.size) return
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    const label = `${selectedKeys.size} 个任务卡片`
    const permanent = view === 'trash'
    const prompt = permanent
      ? `彻底删除选中的 ${label} 及其输出文件？此操作无法撤销。`
      : `将选中的 ${label} 移到回收站？输出文件会保留。`
    if (!window.confirm(prompt)) return

    try {
      let deletedCount = 0
      const removedTaskIds = new Set()
      for (let offset = 0; offset < taskIds.length; offset += 250) {
        const response = await axios.post('/api/tasks/bulk-delete', {
          ids: taskIds.slice(offset, offset + 250),
          permanent,
        })
        deletedCount += Number(response.data.deleted) || 0
        ;[...(response.data.deleted_ids || []), ...(response.data.missing_ids || [])]
          .forEach(taskId => removedTaskIds.add(Number(taskId)))
      }
      setTasks(previous => previous.filter(task => !removedTaskIds.has(Number(task.id))))
      setTotal(previous => Math.max(0, previous - deletedCount))
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      setSelectionMode(false)
      fetchFavoriteGroups()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量删除失败')
    }
  }, [fetchFavoriteGroups, selectedKeys, view])

  const restoreSelected = useCallback(async () => {
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    if (!taskIds.length) return
    try {
      const restored = new Set()
      for (let offset = 0; offset < taskIds.length; offset += 250) {
        const response = await axios.post('/api/tasks/bulk-restore', { ids: taskIds.slice(offset, offset + 250) })
        ;(response.data.restored_ids || []).forEach(taskId => restored.add(Number(taskId)))
      }
      setTasks(previous => previous.filter(task => !restored.has(Number(task.id))))
      setTotal(previous => Math.max(0, previous - restored.size))
      setSelectedKeys(new Set())
      setSelectionUniverse(new Set())
      setSelectionMode(false)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量恢复失败')
    }
  }, [selectedKeys])

  const downloadSelected = useCallback(async (raw = false) => {
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    if (!taskIds.length) return
    try {
      const response = await axios.post('/api/tasks/bulk-download', { ids: taskIds, raw }, { responseType: 'blob' })
      const disposition = response.headers['content-disposition'] || ''
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
      const plainName = disposition.match(/filename="?([^";]+)"?/i)?.[1]
      const timestamp = new Date().toISOString().replace(/\D/g, '').slice(0, 14)
      const filename = encodedName ? decodeURIComponent(encodedName) : (plainName || `ink-traces-tasks-${timestamp}.zip`)
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setBulkDownloadMenuOpen(false)
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量下载失败')
    }
  }, [selectedKeys])

  const addSelectedToGroup = useCallback(async groupId => {
    const taskIds = [...selectedKeys]
      .filter(token => token.startsWith('task-'))
      .map(token => Number(token.slice(5)))
      .filter(Number.isInteger)
    if (!taskIds.length) return
    try {
      for (let offset = 0; offset < taskIds.length; offset += 250) {
        await axios.post('/api/tasks/bulk-favorite-groups', {
          ids: taskIds.slice(offset, offset + 250),
          group_ids: [groupId],
          mode: 'add',
        })
      }
      setBulkGroupMenuOpen(false)
      await fetchFavoriteGroups()
      fetchTasks()
      setError('')
    } catch (requestError) {
      setError(requestError.response?.data?.error || '批量收藏分组失败')
    }
  }, [fetchFavoriteGroups, fetchTasks, selectedKeys])

  const changeView = useCallback(nextView => {
    if (nextView === view) return
    setTasks([])
    setTotal(0)
    setView(nextView)
    if (nextView !== 'favorite') setFavoriteGroup('all')
  }, [view])

  const hasSearchOrFilters = Boolean(query.trim() || activeFilters.length)
  const emptyTitle = hasSearchOrFilters
    ? '没有匹配的任务'
    : view === 'active'
      ? '没有正在生成的任务'
      : view === 'favorite'
        ? '当前收藏为空'
        : view === 'trash'
          ? '回收站为空'
          : mode === 'video' ? '还没有视频任务' : mode === 'audio' ? '还没有音频任务' : '还没有图片任务'

  return (
    <div
      className="task-gallery relative z-10 flex min-h-0 flex-1 flex-col overflow-hidden"
      data-card-size={cardSize}
      data-card-details={cardDetails}
    >
      <div className={`task-gallery-toolbar liquid-glass flex h-13 shrink-0 items-center gap-2 px-3 ${selectionMode ? 'task-gallery-toolbar-selection' : ''}`}>
        <div className="task-gallery-title flex items-center gap-2 text-sm font-semibold text-nexus-text-light">
          <TaskTypeIcon type={mode} />
          {taskTypeLabel(mode)}任务
          <span className="task-gallery-count font-mono text-[10px] font-normal">{categoryTotal}</span>
        </div>
        {selectionMode ? (
          <div data-testid="selection-summary" className="task-selection-summary ml-3 font-mono text-xs text-nexus-text">
            已选 <span className="text-nexus-green">{selectedKeys.size}</span>
            <span className="ml-2 text-[10px] text-nexus-muted">共 {categoryTotal}</span>
          </div>
        ) : (
          <div className="task-view-segment ml-3 flex items-center gap-1" role="group" aria-label="任务视图">
            <button type="button" aria-pressed={view === 'all'} onClick={() => changeView('all')} className={`task-view-button ${view === 'all' ? 'task-view-button-active' : ''}`}>全部</button>
            <button type="button" aria-pressed={view === 'favorite'} onClick={() => changeView('favorite')} className={`task-view-button ${view === 'favorite' ? 'task-view-button-active' : ''}`}><Heart size={12} /> 收藏</button>
            <button type="button" aria-pressed={view === 'active'} onClick={() => changeView('active')} className={`task-view-button ${view === 'active' ? 'task-view-button-active' : ''}`}><LoaderCircle size={12} /> 进行中</button>
            <button type="button" aria-pressed={view === 'trash'} onClick={() => changeView('trash')} className={`task-view-button ${view === 'trash' ? 'task-view-button-active' : ''}`}><Trash2 size={12} /> 回收站</button>
          </div>
        )}
        {!selectionMode && view === 'favorite' && (
          <div ref={groupMenuRef} className="relative">
            <button
              type="button"
              aria-label="筛选收藏分组"
              aria-haspopup="menu"
              aria-expanded={groupMenuOpen}
              onClick={() => setGroupMenuOpen(open => !open)}
              className="favorite-group-filter"
            >
              <FolderHeart size={13} />
              <span className="max-w-24 truncate">{favoriteGroupLabel}</span>
              <ChevronRight size={12} className={`transition-transform ${groupMenuOpen ? 'rotate-90' : ''}`} />
            </button>
            <AnimatePresence>
              {groupMenuOpen && (
                <motion.div
                  role="menu"
                  aria-label="收藏分组"
                  className="task-group-menu absolute left-0 top-[calc(100%+8px)] z-50 w-64 p-2"
                  initial={{ opacity: 0, y: -5, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.98 }}
                >
                  <button type="button" role="menuitemradio" aria-checked={favoriteGroup === 'all'} onClick={() => { setFavoriteGroup('all'); setGroupMenuOpen(false) }} className="task-group-option">
                    <span className="task-layout-check">{favoriteGroup === 'all' && <Check size={12} />}</span>
                    <span className="truncate">全部收藏</span>
                  </button>
                  <button type="button" role="menuitemradio" aria-checked={favoriteGroup === 'ungrouped'} onClick={() => { setFavoriteGroup('ungrouped'); setGroupMenuOpen(false) }} className="task-group-option">
                    <span className="task-layout-check">{favoriteGroup === 'ungrouped' && <Check size={12} />}</span>
                    <span className="truncate">未分组</span>
                  </button>
                  {favoriteGroups.length > 0 && <div className="task-layout-divider" />}
                  <div className="custom-scrollbar max-h-56 overflow-y-auto">
                    {favoriteGroups.map(group => (
                      <div key={group.id} className="task-group-row">
                        {editingGroupId === group.id ? (
                          <form className="flex min-w-0 flex-1 items-center gap-1" onSubmit={event => { event.preventDefault(); saveFavoriteGroup(group.id) }}>
                            <input
                              value={editingGroupName}
                              onChange={event => setEditingGroupName(event.target.value)}
                              aria-label={`重命名分组 ${group.name}`}
                              autoFocus
                              maxLength={40}
                              className="task-group-input min-w-0 flex-1"
                            />
                            <IconButton label="保存分组名称" type="submit" className="size-7"><Check size={12} /></IconButton>
                          </form>
                        ) : (
                          <>
                            <button
                              type="button"
                              role="menuitemradio"
                              aria-checked={Number(favoriteGroup) === Number(group.id)}
                              onClick={() => { setFavoriteGroup(group.id); setGroupMenuOpen(false) }}
                              className="task-group-row-main"
                            >
                              <span className="favorite-group-dot" data-color={group.color} />
                              <span className="min-w-0 flex-1 truncate">{group.name}</span>
                              <span className="font-mono text-[9px] text-nexus-muted">{group.task_count || 0}</span>
                            </button>
                            <IconButton label={`重命名分组 ${group.name}`} onClick={() => { setEditingGroupId(group.id); setEditingGroupName(group.name) }} className="size-7"><Pencil size={11} /></IconButton>
                            <IconButton label={`删除分组 ${group.name}`} onClick={() => removeFavoriteGroup(group)} className="size-7 hover:text-nexus-red"><Trash2 size={11} /></IconButton>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="task-layout-divider" />
                  <div className="favorite-group-swatches" role="radiogroup" aria-label="新分组颜色">
                    {GROUP_COLORS.map(color => (
                      <button
                        key={color}
                        type="button"
                        role="radio"
                        aria-label={`${color} 分组颜色`}
                        aria-checked={newGroupColor === color}
                        onClick={() => setNewGroupColor(color)}
                        className="favorite-group-swatch"
                        data-color={color}
                      >
                        {newGroupColor === color && <Check size={10} />}
                      </button>
                    ))}
                  </div>
                  <form onSubmit={createFavoriteGroup} className="flex items-center gap-1.5 p-1">
                    <input value={newGroupName} onChange={event => setNewGroupName(event.target.value)} maxLength={40} aria-label="新收藏分组名称" placeholder="新分组" className="task-group-input min-w-0 flex-1" />
                    <IconButton label="创建收藏分组" type="submit" disabled={!newGroupName.trim()} className="size-8"><FolderPlus size={13} /></IconButton>
                  </form>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
        {!selectionMode && (
          <div className="relative ml-auto w-48">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-muted" />
            <input value={query} onChange={event => setQuery(event.target.value)} aria-label="搜索任务画廊" placeholder="搜索任务、ID、端点" className="glass-input h-8 w-full pl-8 pr-2 text-xs outline-none" />
          </div>
        )}
        {!selectionMode && (
          <div ref={filterMenuRef} className="relative">
            <IconButton
              label="筛选任务"
              aria-haspopup="menu"
              aria-expanded={filterMenuOpen}
              onClick={() => setFilterMenuOpen(open => !open)}
              className={filterMenuOpen || activeFilters.length ? 'text-nexus-cyan' : ''}
            >
              <Filter size={15} />
              {activeFilters.length > 0 && <span className="task-filter-count">{activeFilters.length}</span>}
            </IconButton>
            <AnimatePresence>
              {filterMenuOpen && (
                <motion.div
                  role="menu"
                  aria-label="任务筛选"
                  className="task-filter-menu absolute right-0 top-[calc(100%+8px)] z-50 w-72 p-3"
                  initial={{ opacity: 0, y: -5, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.98 }}
                >
                  <div className="mb-3 flex items-center gap-2">
                    <Filter size={13} className="text-nexus-cyan" />
                    <span className="text-xs font-semibold text-nexus-text-light">筛选任务</span>
                    <button type="button" onClick={clearFilters} disabled={!activeFilters.length} className="ml-auto text-[10px] text-nexus-muted hover:text-nexus-text-light disabled:opacity-35">全部清除</button>
                  </div>
                  <label className="task-filter-field">
                    <span>状态</span>
                    <select aria-label="按任务状态筛选" value={filters.status} onChange={event => setFilters(previous => ({ ...previous, status: event.target.value }))}>
                      {STATUS_FILTER_OPTIONS.map(option => <option key={option.value || 'all'} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                  <label className="task-filter-field">
                    <span>端点</span>
                    <select aria-label="按任务端点筛选" value={filters.provider} onChange={event => setFilters(previous => ({ ...previous, provider: event.target.value }))}>
                      <option value="">全部端点</option>
                      {filterOptions.providers.map(provider => <option key={provider} value={provider}>{providerLabel(provider)}</option>)}
                    </select>
                  </label>
                  <label className="task-filter-field">
                    <span>模型</span>
                    <select aria-label="按任务模型筛选" value={filters.model} onChange={event => setFilters(previous => ({ ...previous, model: event.target.value }))}>
                      <option value="">全部模型</option>
                      {filterOptions.models.map(model => <option key={model} value={model}>{model}</option>)}
                    </select>
                  </label>
                  <label className="task-filter-field">
                    <span>创建时间</span>
                    <select aria-label="按任务日期筛选" value={filters.dateRange} onChange={event => setFilters(previous => ({ ...previous, dateRange: event.target.value }))}>
                      {DATE_FILTER_OPTIONS.map(option => <option key={option.value || 'all'} value={option.value}>{option.label}</option>)}
                    </select>
                  </label>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
        <div ref={layoutMenuRef} className={`relative ${selectionMode ? 'ml-auto' : ''}`}>
          <IconButton
            label="任务卡片布局"
            aria-haspopup="menu"
            aria-expanded={layoutMenuOpen}
            onClick={() => setLayoutMenuOpen(open => !open)}
            className={layoutMenuOpen ? 'text-nexus-green' : ''}
          >
            <LayoutGrid size={15} />
          </IconButton>
          <AnimatePresence>
            {layoutMenuOpen && (
              <motion.div
                role="menu"
                aria-label="任务卡片布局设置"
                className="task-layout-menu absolute right-0 top-[calc(100%+8px)] z-50 w-48 p-2"
                initial={{ opacity: 0, y: -5, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -4, scale: 0.98 }}
              >
                <div className="task-layout-heading">卡片尺寸</div>
                {CARD_SIZE_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={cardSize === option.value}
                    onClick={() => updateGalleryPreference('cardSize', option.value)}
                    className="task-layout-option"
                  >
                    <span className="task-layout-check">{cardSize === option.value && <Check size={12} />}</span>
                    {option.label}
                  </button>
                ))}
                <div className="task-layout-divider" />
                <div className="task-layout-heading">卡片内容</div>
                {CARD_DETAIL_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={cardDetails === option.value}
                    onClick={() => updateGalleryPreference('cardDetails', option.value)}
                    className="task-layout-option"
                  >
                    <span className="task-layout-check">{cardDetails === option.value && <Check size={12} />}</span>
                    {option.label}
                  </button>
                ))}
                <div className="task-layout-divider" />
                <div className="task-layout-heading flex items-center gap-1.5"><SortDesc size={11} /> 排序</div>
                {SORT_OPTIONS.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={cardSort === option.value}
                    onClick={() => updateGalleryPreference('sort', option.value)}
                    className="task-layout-option"
                  >
                    <span className="task-layout-check">{cardSort === option.value && <Check size={12} />}</span>
                    {option.label}
                  </button>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        <IconButton
          label={selectionMode ? '退出批量选择' : '批量选择任务'}
          aria-pressed={selectionMode}
          onClick={toggleSelectionMode}
          className={selectionMode ? 'text-nexus-green' : ''}
        >
          {selectionMode ? <X size={15} /> : <ListChecks size={15} />}
        </IconButton>
        {selectionMode ? (
          <>
            <IconButton
              label={allCategorySelected ? '取消全选' : '全选当前分类'}
              onClick={toggleSelectAll}
              disabled={selectingAll || categoryTotal === 0}
              className={allCategorySelected ? 'text-nexus-green' : ''}
            >
              <CheckCheck size={15} className={selectingAll ? 'animate-pulse' : ''} />
            </IconButton>
            <IconButton
              label={selectedTaskCount >= 2 && selectedTaskCount <= 4 ? '对比已选任务' : '选择 2 到 4 个任务进行对比'}
              onClick={openSelectedComparison}
              disabled={compareLoading || selectedTaskCount < 2 || selectedTaskCount > 4}
              className="hover:text-nexus-cyan"
            >
              <Columns3 size={15} className={compareLoading ? 'animate-pulse' : ''} />
            </IconButton>
            {mode === 'image' ? (
              <div ref={bulkDownloadMenuRef} className="relative">
                <IconButton
                  label="下载已选任务结果"
                  aria-haspopup="menu"
                  aria-expanded={bulkDownloadMenuOpen}
                  onClick={() => setBulkDownloadMenuOpen(open => !open)}
                  disabled={selectedTaskCount === 0}
                  className={bulkDownloadMenuOpen ? 'text-nexus-green' : ''}
                >
                  <Download size={15} />
                </IconButton>
                <AnimatePresence>
                  {bulkDownloadMenuOpen && (
                    <motion.div
                      role="menu"
                      aria-label="批量图片下载选项"
                      className="task-layout-menu absolute right-0 top-[calc(100%+8px)] z-50 w-48 p-2"
                      initial={{ opacity: 0, y: -5, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -4, scale: 0.98 }}
                    >
                      <button type="button" role="menuitem" onClick={() => downloadSelected(false)} className="task-group-option">
                        <Download size={14} /> 带生成参数
                      </button>
                      <button type="button" role="menuitem" onClick={() => downloadSelected(true)} className="task-group-option">
                        <ImageIcon size={14} /> 原始生成图
                      </button>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ) : (
              <IconButton
                label="下载已选任务结果"
                onClick={() => downloadSelected(false)}
                disabled={selectedTaskCount === 0}
              >
                <Download size={15} />
              </IconButton>
            )}
            {view !== 'trash' && favoriteGroups.length > 0 && (
              <div ref={bulkGroupMenuRef} className="relative">
                <IconButton
                  label="将已选任务加入收藏分组"
                  aria-haspopup="menu"
                  aria-expanded={bulkGroupMenuOpen}
                  onClick={() => setBulkGroupMenuOpen(open => !open)}
                  disabled={selectedTaskCount === 0}
                  className={bulkGroupMenuOpen ? 'text-nexus-cyan' : ''}
                >
                  <FolderHeart size={15} />
                </IconButton>
                <AnimatePresence>
                  {bulkGroupMenuOpen && (
                    <motion.div
                      role="menu"
                      aria-label="批量加入收藏分组"
                      className="task-group-menu absolute right-0 top-[calc(100%+8px)] z-50 w-52 p-2"
                      initial={{ opacity: 0, y: -5, scale: 0.98 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -4, scale: 0.98 }}
                    >
                      <div className="task-layout-heading">加入分组</div>
                      {favoriteGroups.map(group => (
                        <button key={group.id} type="button" role="menuitem" onClick={() => addSelectedToGroup(group.id)} className="task-group-option">
                          <span className="favorite-group-dot" data-color={group.color} />
                          <span className="truncate">{group.name}</span>
                        </button>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}
            {view === 'trash' && (
              <IconButton label="恢复已选任务" onClick={restoreSelected} disabled={selectedTaskCount === 0}>
                <ArchiveRestore size={15} />
              </IconButton>
            )}
            <IconButton
              label={view === 'trash' ? '彻底删除已选任务' : '将已选任务移到回收站'}
              onClick={deleteSelected}
              disabled={!selectedKeys.size}
              className="hover:text-nexus-red"
            >
              <Trash2 size={15} />
            </IconButton>
          </>
        ) : (
          <IconButton label="刷新任务" onClick={() => fetchTasks()}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></IconButton>
        )}
      </div>

      {!selectionMode && activeFilters.length > 0 && (
        <div className="task-filter-strip flex h-10 shrink-0 items-center gap-2 px-3" aria-label="已应用筛选">
          <span className="flex items-center gap-1.5 text-[10px] text-nexus-muted"><Filter size={11} /> 已筛选</span>
          {activeFilters.map(filter => (
            <button
              key={filter.key}
              type="button"
              aria-label={`移除筛选 ${filter.label}`}
              onClick={() => setFilters(previous => ({ ...previous, [filter.key]: '' }))}
              className="task-filter-chip"
            >
              <span className="max-w-36 truncate">{filter.label}</span><X size={11} />
            </button>
          ))}
          <button type="button" onClick={clearFilters} className="ml-auto text-[10px] text-nexus-muted hover:text-nexus-text-light">清除全部</button>
        </div>
      )}

      <div className="custom-scrollbar flex-1 overflow-y-auto p-3">
        {error && (
          <div role="alert" className="mb-3 flex min-h-9 items-center gap-2 rounded border border-nexus-red/25 bg-nexus-red/10 px-3 text-xs text-nexus-red">
            <AlertTriangle size={13} /> {error}
          </div>
        )}
        <TaskCardList
          items={visibleItems}
          loading={loading}
          detailed={cardDetails === 'detailed'}
          selectionMode={selectionMode}
          selectedKeys={selectedKeys}
          onOpen={openItem}
          onToggleSelection={toggleSelection}
          onFavorite={toggleFavorite}
          onCancel={cancelTask}
          onDelete={deleteTask}
          trash={view === 'trash'}
        />
        {!loading && visibleItems.length === 0 && (
          <div className="task-empty-state">
            <div className="task-empty-icon"><TaskTypeIcon type={mode} size={22} /></div>
            <div className="text-sm font-medium text-nexus-text-light">{emptyTitle}</div>
            <div className="font-mono text-[10px] text-nexus-muted">{hasSearchOrFilters ? 'FILTER RESULT: 0' : `${mode.toUpperCase()} TASKS: 0`}</div>
            {hasSearchOrFilters && (
              <button type="button" onClick={clearSearchAndFilters} className="btn-base btn-outline mt-2 min-h-8 text-xs">清除筛选</button>
            )}
          </div>
        )}
        {!selectionMode && tasks.length < total && (
          <button
            type="button"
            disabled={loading}
            onClick={() => fetchTasks({ append: true, offset: tasks.length })}
            className="btn-base btn-outline mx-auto mt-3 flex min-w-40 text-xs"
          >
            {loading ? '加载中' : `加载更多 (${tasks.length}/${total})`}
          </button>
        )}
      </div>

      <AnimatePresence>
        {selectedItem && (
          <TaskDetailModal
            item={selectedItem}
            position={selectedPosition}
            total={selectedTotal}
            onPrevious={() => navigate(-1)}
            onNext={() => navigate(1)}
            onClose={() => { setSelectedKey(null); setSelectedOverride(null) }}
            onFavorite={toggleFavorite}
            onDelete={deleteTask}
            onReuse={onReuseTask}
            onCancel={cancelTask}
            onRetry={retryTask}
            onRestore={restoreTask}
            onSetGroup={toggleItemGroup}
            favoriteGroups={favoriteGroups}
            trash={view === 'trash'}
          />
        )}
      </AnimatePresence>
      {retryConfirm && (
        <ConfirmDialog
          title="重试结果未知的任务？"
          confirmLabel="确认重试（可能重复计费）"
          danger
          onClose={() => setRetryConfirm(null)}
          onConfirm={() => retryTask(retryConfirm, true)}
        >
          <p>任务 #{retryConfirm.taskId} 的请求已发出但未确认结果{retryConfirm.resultUnknownReason ? `（${retryConfirm.resultUnknownReason}）` : ''}，<strong>供应商可能已经计费</strong>。</p>
          <p>重试会创建新的任务并再次提交，<strong>可能重复计费</strong>。建议先到供应商控制台核查原任务结果。</p>
        </ConfirmDialog>
      )}
      <AnimatePresence>
        {compareItems.length >= 2 && (
          <TaskCompareModal
            items={compareItems}
            onClose={() => setCompareItems([])}
            onReuse={onReuseTask}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

const MemoTaskGallery = React.memo(TaskGallery)

export default function TaskGalleryBoundary({ mode, refreshToken, onReuseTask }) {
  const reuseTask = useLiveCallback(onReuseTask)
  return <MemoTaskGallery mode={mode} refreshToken={refreshToken} onReuseTask={reuseTask} />
}
