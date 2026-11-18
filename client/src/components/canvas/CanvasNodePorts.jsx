import React from 'react'
import {portAriaLabel,groupAriaLabel} from '../../lib/canvasPortLayout'
import './canvasChrome.css'
import './canvasPorts.css'

const KIND = {image:'图片',video:'视频',audio:'音频'}

// CANVAS-PORTS-UI-20261118 (spec §4.2/4.3): left reference ports of a generation node, one per resolved
// reference (number = @图片N = submission order), dashed "待生成" ports, and one empty port per group unless the
// group is full. Port names are visible only while the node is selected / hovered / a connection is dragged
// (CSS); aria-labels always carry them. A stack taller than the card is folded to one port per group.
export default function CanvasNodePorts({node,ports,layout,dragKind=null,dragReason=null,dropTarget=false,onPointerDown,onPort,onExpand}) {
  const hint = ports.hint
  return <div className="cv-ports" data-testid="node-ports" data-collapsed={layout.collapsed ? 'true' : undefined}>
    {layout.items.map(item => {
      if (item.type === 'group') {
        const {group} = item, over = group.overLimit > 0
        return <button key={`group-${group.kind}`} type="button" className={`cv-port cv-port-in cv-port-group is-${group.kind} ${over ? 'is-over' : ''} ${group.conflict ? 'is-conflict' : ''}`} style={{top:item.y - 13}} data-port-kind={group.kind} data-port-group="true" aria-label={groupAriaLabel(node,group)} title={`${KIND[group.kind]}参考 ${group.count} 个${over ? `，${group.overLimit} 个超出上限` : ''}`} onPointerDown={onPointerDown} onClick={() => onExpand?.(group)}><span className="cv-port-badge" aria-hidden="true">{KIND[group.kind]} {group.count}</span></button>
      }
      const {port} = item, empty = port.source === 'empty', ready = !!dragKind && !dragReason && empty && port.kind === dragKind
      const tooltip = [portAriaLabel(node,port), empty && port.reason ? port.reason : '', !empty && port.source !== 'pending' ? '松开连线到此口：插入为该类型第 N 位' : ''].filter(Boolean).join('\n')
      return <button key={`${port.kind}-${port.source}-${port.assetId || port.edgeId || 'empty'}`} type="button"
        className={`cv-port cv-port-in cv-port-ref is-${port.kind} is-${port.source} ${port.overLimit ? 'is-over' : ''} ${port.role ? `is-${port.role}` : ''} ${ready ? 'is-drop-ready' : ''}`}
        style={{top:item.y - 13}} data-port-kind={port.kind} data-port-index={port.index ?? undefined} data-port-source={port.source}
        aria-label={portAriaLabel(node,port)} title={tooltip} onPointerDown={onPointerDown} onClick={() => onPort?.(port)}>
        <span className="cv-port-name" aria-hidden="true">{port.label}{port.overLimit ? ' · 超出上限' : ''}</span>
      </button>
    })}
    {hint && dragKind && !dragReason && <span className="cv-port-hint" aria-hidden="true">{hint}</span>}
    {dropTarget && dragReason && <span className="cv-port-refusal" role="alert">{dragReason}</span>}
  </div>
}
