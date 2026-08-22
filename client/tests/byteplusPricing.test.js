import test from 'node:test'
import assert from 'node:assert/strict'

import {
  estimateBytePlusVideoCost,
  formatUsdEstimate,
} from '../src/lib/byteplusPricing.js'

const ACTIVE_PROMOTION_DATE = Date.parse('2026-08-22T00:00:00Z')
const AFTER_PROMOTION_DATE = Date.parse('2026-09-18T00:00:00Z')

test('estimates Seedance 2.0 against the documented 720p example', () => {
  const estimate = estimateBytePlusVideoCost({
    model: 'seedance-2.0',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
  })

  assert.equal(estimate.minimumTokens, 108_000)
  assert.equal(estimate.unitPrice, 7.0)
  assert.equal(formatUsdEstimate(estimate), '$0.76')
})

test('prices Seedance 2.5 with the official input-specific rates', () => {
  const withoutVideo = estimateBytePlusVideoCost({
    model: 'seedance-2.5',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
  })
  const withVideo = estimateBytePlusVideoCost({
    model: 'seedance-2.5',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
    referenceVideos: [{ url: '/reference.mp4', duration: 5 }],
  })

  assert.equal(withoutVideo.unitPrice, 10.70)
  assert.equal(withVideo.unitPrice, 6.40)
  assert.equal(formatUsdEstimate(withoutVideo), '$1.16')
  assert.equal(formatUsdEstimate(withVideo), '$1.38')
})

test('uses Seedance 2.5 pricing dimensions for the Cupsy moderated model', () => {
  const standard = estimateBytePlusVideoCost({
    model: 'seedance-2.5', resolution: '720p', ratio: '16:9', duration: 5,
  })
  const moderated = estimateBytePlusVideoCost({
    model: 'seedance-2.5-moderated', resolution: '720p', ratio: '16:9', duration: 5,
  })

  assert.equal(moderated.model, 'seedance-2.5')
  assert.equal(moderated.minimumCost, standard.minimumCost)
  assert.equal(moderated.maximumCost, standard.maximumCost)
})

test('applies the current BytePlus Seedance 2.5 1080p promotion', () => {
  const promoted = estimateBytePlusVideoCost({
    model: 'seedance-2.5', provider: 'ark', resolution: '1080p',
    ratio: '16:9', duration: 5, now: ACTIVE_PROMOTION_DATE,
  })
  const listPrice = estimateBytePlusVideoCost({
    model: 'seedance-2.5', provider: 'ark', resolution: '1080p',
    ratio: '16:9', duration: 5, now: AFTER_PROMOTION_DATE,
  })
  const cupsy = estimateBytePlusVideoCost({
    model: 'seedance-2.5-moderated', provider: 'cupsy', resolution: '1080p',
    ratio: '16:9', duration: 5, now: ACTIVE_PROMOTION_DATE,
  })
  const promotedWithVideo = estimateBytePlusVideoCost({
    model: 'seedance-2.5', provider: 'ark', resolution: '1080p',
    ratio: '16:9', duration: 5, now: ACTIVE_PROMOTION_DATE,
    referenceVideos: [{ url: '/reference.mp4', duration: 5 }],
  })

  assert.equal(promoted.width, 1920)
  assert.equal(promoted.height, 1080)
  assert.equal(promoted.listUnitPrice, 11.70)
  assert.equal(promoted.unitPrice, 11.70 * 0.72)
  assert.equal(promoted.promotionActive, true)
  assert.equal(formatUsdEstimate(promoted), '$2.05')
  assert.equal(formatUsdEstimate(listPrice), '$2.84')
  assert.equal(formatUsdEstimate(cupsy), '$2.84')
  assert.equal(promotedWithVideo.listUnitPrice, 7.00)
  assert.equal(promotedWithVideo.unitPrice, 7.00 * 0.72)
  assert.equal(formatUsdEstimate(promotedWithVideo), '$2.45')
})

test('uses actual reference duration and the four-second billing floor', () => {
  const shortReference = estimateBytePlusVideoCost({
    model: 'seedance-2.0',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
    referenceVideos: [{ url: '/reference.mp4', duration: 2 }],
  })
  const measuredReference = estimateBytePlusVideoCost({
    model: 'seedance-2.0',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
    referenceVideos: [{ url: '/reference.mp4', duration: 8 }],
  })

  assert.equal(shortReference.inputVideoSeconds, 4)
  assert.equal(formatUsdEstimate(shortReference), '$0.84')
  assert.equal(measuredReference.inputVideoSeconds, 8)
  assert.equal(measuredReference.inputDurationAssumed, false)
})

test('returns a model-specific range for automatic duration', () => {
  const estimate = estimateBytePlusVideoCost({
    model: 'seedance-2.5',
    resolution: '480p',
    ratio: '9:16',
    duration: -1,
  })

  assert.equal(estimate.minimumOutputSeconds, 4)
  assert.equal(estimate.maximumOutputSeconds, 30)
  assert.equal(formatUsdEstimate(estimate), '$0.41~$3.08')
})

test('falls back to five seconds only when reference duration is unknown', () => {
  const estimate = estimateBytePlusVideoCost({
    model: 'seedance-2.0',
    resolution: '480p',
    ratio: 'adaptive',
    duration: 5,
    referenceVideos: [{ url: '/unknown.mp4' }],
  })

  assert.equal(estimate.inputVideoSeconds, 5)
  assert.equal(estimate.inputDurationAssumed, true)
  assert.equal(estimate.ratioAssumed, true)
  assert.equal(estimate.billedRatio, '16:9')
})
