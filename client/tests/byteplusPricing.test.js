import test from 'node:test'
import assert from 'node:assert/strict'

import {
  estimateBytePlusVideoCost,
  formatCnyEstimate,
} from '../src/lib/byteplusPricing.js'

test('estimates Seedance 2.0 against the documented 720p example', () => {
  const estimate = estimateBytePlusVideoCost({
    model: 'seedance-2.0',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
  })

  assert.equal(estimate.minimumTokens, 108_000)
  assert.equal(formatCnyEstimate(estimate), '¥4.97')
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

  assert.equal(withoutVideo.unitPrice, 46 * (10.70 / 7.00))
  assert.equal(withVideo.unitPrice, 28 * (6.40 / 4.30))
  assert.equal(formatCnyEstimate(withoutVideo), '¥7.59')
  assert.equal(formatCnyEstimate(withVideo), '¥9.00')
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
  assert.equal(formatCnyEstimate(shortReference), '¥5.44')
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
  assert.match(formatCnyEstimate(estimate), /^¥\d+\.\d{2}~¥\d+\.\d{2}$/)
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
