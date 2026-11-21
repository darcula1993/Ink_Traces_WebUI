import React from 'react'
import { describeLayerEstimate } from '../lib/byteplusPricing'

// Layer decomposition is billed per actual output layer (base image included).
// Seedream 5.5 bounds the output count via max_images (default 12), so show the
// 1..N USD range (3 decimals); unknown/invalid states never show $0.
export default function LayerCostEstimate({
  modern,
  modelKnown = true,
  size,
  maxImages = 12,
  providerUnavailable = false,
  unavailableReason = '',
}) {
  if (!modelKnown) {
    return (
      <span
        className="layer-cost-estimate"
        data-testid="layer-cost-estimate"
        title="正在读取图层接口配置，暂不估价；不代表免费"
      >
        费用待估
      </span>
    )
  }
  if (providerUnavailable) {
    const title = `${unavailableReason || '当前图层接口不可用，无法估算费用'}；不代表免费`
    return (
      <span
        className="layer-cost-estimate"
        data-testid="layer-cost-estimate"
        title={title}
        aria-label={`预估费用 未知。${title}`}
      >
        费用未知
      </span>
    )
  }
  const { text, detail, unit } = describeLayerEstimate({ modern, size })
  if (modern) {
    const validMax = Number.isInteger(maxImages) && maxImages >= 2 && maxImages <= 100
    if (!validMax) {
      const title = '输出层数须为 2–100 的整数，暂无法估算区间费用；不代表免费'
      return (
        <span
          className="layer-cost-estimate"
          data-testid="layer-cost-estimate"
          title={title}
          aria-label={`预估费用 未知。${title}`}
        >
          费用未知
        </span>
      )
    }
    const minTotal = unit.inputCost + unit.perLayerMin
    const maxTotal = unit.inputCost + maxImages * unit.perLayerMax
    const rangeText = `$${minTotal.toFixed(3)}–$${maxTotal.toFixed(3)} USD`
    const label = `预估 ${rangeText}（1–${maxImages} 层）`
    const fullDetail = `${detail}；按 1 层底图至 ${maxImages} 层估算约 ${rangeText}（含源图）`
    return (
      <span
        className="layer-cost-estimate"
        data-testid="layer-cost-estimate"
        title={fullDetail}
        aria-label={`预估费用 ${rangeText}（1 至 ${maxImages} 层）。${fullDetail}`}
      >
        {label}
      </span>
    )
  }
  const minOneLayer = (unit.inputCost + unit.perLayerMin).toFixed(3)
  const fullDetail = `${detail}；1 层底图起约 $${minOneLayer} USD，上限层数未知，按实际输出计`
  return (
    <span
      className="layer-cost-estimate"
      data-testid="layer-cost-estimate"
      title={fullDetail}
      aria-label={`预估费用 ${text}。${fullDetail}`}
    >
      {text}
    </span>
  )
}
