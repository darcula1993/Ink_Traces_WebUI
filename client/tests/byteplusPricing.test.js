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

test('prices Seedance 2.5 at 1.5 times Seedance 2.0', () => {
  const seedance20 = estimateBytePlusVideoCost({
    model: 'seedance-2.0',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
  })
  const seedance25 = estimateBytePlusVideoCost({
    model: 'seedance-2.5',
    resolution: '720p',
    ratio: '16:9',
    duration: 5,
  })

  assert.equal(seedance25.minimumCost, seedance20.minimumCost * 1.5)
  assert.equal(formatCnyEstimate(seedance25), '¥7.45')
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
