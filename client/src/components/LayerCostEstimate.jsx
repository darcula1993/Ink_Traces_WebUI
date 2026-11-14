import React from 'react'
import {describeLayerEstimate} from '../lib/byteplusPricing'

// Layer decomposition is billed per actual output layer (base image included), so the
// pre-submission figure is a per-layer unit price; the ledger multiplies by real layers.
export default function LayerCostEstimate({modern,modelKnown=true,size}){
 if(!modelKnown)return <span className="layer-cost-estimate" data-testid="layer-cost-estimate" title="正在读取图层接口配置，暂不估价；不代表免费">费用待估</span>
 const {text,detail}=describeLayerEstimate({modern,size})
 return <span className="layer-cost-estimate" data-testid="layer-cost-estimate" title={detail} aria-label={`预估费用 ${text}。${detail}`}>{text}</span>
}
