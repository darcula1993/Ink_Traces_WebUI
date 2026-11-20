"""Server port of the browser's mention reconciliation (GROUP-RUN-20261115 rework, QA D3).

Line-by-line port of ``reconcileReferenceMentions`` (client/src/lib/canvasReferenceOrder.js)
with ``bindReferenceMentions`` / ``positionalMentionRebinds`` (canvasReferences.js), so a
server write-back renumbers ``@图片N`` tokens and follows bindings exactly as an open page
would.  Without it a closed page kept ``@图片1`` while the first reference became the
upstream's new result (silently changing what the prompt points at).

Identity checks of the JS original (``a !== b`` on arrays/objects) become value
equality: the server never keeps two equal copies that the browser would treat as
different objects.  Shared cases: server/tests/data/canvas_rebind_cases.json, run by
server/tests/test_canvas_reference_rebind.py and client/tests/canvasRebindParity.test.js.
"""
from canvas_submit import (REFERENCE_TOKEN, _truthy, canvas_mention_items, positional_mention_rebinds,
                           reference_tokens, resolve_node_inputs)

GENERATION_TYPES = ('image', 'video', 'audio')
_FRAME_KEYS = ('video_mode', 'first_frame', 'last_frame')
_MISSING = object()


def _asset_id(node):
    asset = node.get('asset') if isinstance(node, dict) else None
    return asset.get('id') if isinstance(asset, dict) else None


def _param(node, key):
    params = node.get('params')
    return params.get(key, _MISSING) if isinstance(params, dict) else _MISSING


def _token_prefix(token):
    return token.rstrip('0123456789')


def bind_reference_mentions(node, assets, text):
    items = canvas_mention_items(node, assets)
    current = {item['token']: item for item in items}
    mentions = node.get('referenceMentions') if isinstance(node.get('referenceMentions'), dict) else {}
    tokens = reference_tokens(text)
    bindings = {}
    for token in tokens:
        saved = mentions.get(token)
        if _truthy(saved):
            bindings[token] = saved
    used = set(bindings.values())
    for token in tokens:
        if token in bindings:
            continue
        target = current.get(token)
        if not target:
            continue
        asset_id = target['assetId']
        if _truthy(asset_id) and asset_id not in used:
            bindings[token] = asset_id
            used.add(asset_id)
            continue
        prefix = _token_prefix(token)
        fallback = next((item['assetId'] for item in items
                         if _token_prefix(item['token']) == prefix and _truthy(item['assetId']) and item['assetId'] not in used), None)
        if _truthy(fallback):
            bindings[token] = fallback
            used.add(fallback)
    return bindings


def _unchanged(before, after):
    previous = {node.get('id'): node for node in before['nodes']}
    if before['edges'] != after['edges'] or len(before['nodes']) != len(after['nodes']):
        return False
    for node in after['nodes']:
        old = previous.get(node.get('id'))
        if old is None or _asset_id(old) != _asset_id(node):
            return False
        for key in ('text', 'referenceAssets', 'referenceOrder', 'referenceMentions'):
            if old.get(key, _MISSING) != node.get(key, _MISSING):
                return False
        if any(_param(old, key) != _param(node, key) for key in _FRAME_KEYS):
            return False
    return True


def _reconcile_node(original, before, after, previous):
    old = previous.get(original.get('id'))
    old_inputs = resolve_node_inputs(old, before['nodes'], before['edges']) if old else None
    node = original
    next_inputs = resolve_node_inputs(node, after['nodes'], after['edges'])
    explicit = bool(old) and original.get('referenceMentions', _MISSING) != old.get('referenceMentions', _MISSING)
    old_bindings = bind_reference_mentions(old, old_inputs['assets'], old_inputs['prompt']) if old else {}
    if explicit:
        bindings = dict(original.get('referenceMentions') or {})
    else:
        bindings = bind_reference_mentions({**node, 'referenceMentions': old_bindings}, next_inputs['assets'], next_inputs['prompt'])
    ids = {asset.get('id') for asset in next_inputs['assets']}
    replacements = {}
    for asset_id in dict.fromkeys([*((old or {}).get('referenceOrder') or []), *bindings.values()]):
        if asset_id in ids:
            continue
        sources = [edge for edge in before['edges'] if edge.get('target') == node.get('id')
                   and _asset_id(previous.get(edge.get('source'))) == asset_id]
        candidates = set()
        for edge in sources:
            if not any(e.get('source') == edge.get('source') and e.get('target') == node.get('id') for e in after['edges']):
                continue
            source = next((item for item in after['nodes'] if item.get('id') == edge.get('source')), None)
            value = _asset_id(source)
            if _truthy(value) and value in ids:
                candidates.add(value)
        if len(candidates) == 1:
            replacements[asset_id] = next(iter(candidates))
    order = node.get('referenceOrder')
    if order and any(item in replacements for item in order):
        node = {**node, 'referenceOrder': list(dict.fromkeys(replacements.get(item) or item for item in order))}
        next_inputs = resolve_node_inputs(node, after['nodes'], after['edges'])
    for token in list(bindings):
        bindings[token] = replacements.get(bindings[token]) or bindings[token]
    if not explicit:
        for item in positional_mention_rebinds(node, next_inputs['assets'], bindings, str(next_inputs['prompt'])):
            bindings[item['token']] = item['to']
    by_id = {}
    for item in canvas_mention_items(node, next_inputs['assets']):
        by_id[item['assetId']] = item['token']
    upstream = '\n'.join(
        (source.get('text') or '') for source in
        (next((n for n in after['nodes'] if n.get('id') == edge.get('source')), None)
         for edge in after['edges'] if edge.get('target') == node.get('id'))
        if isinstance(source, dict) and source.get('type') == 'text')
    upstream_tokens = reference_tokens(upstream)
    safe = all(value in by_id for value in bindings.values()) and all(
        not _truthy(bindings.get(token)) or by_id.get(bindings.get(token)) == token for token in upstream_tokens)
    text = node.get('text', _MISSING)
    if safe:
        text = REFERENCE_TOKEN.sub(lambda match: by_id.get(bindings.get(match.group(0))) or match.group(0),
                                   node.get('text') or '')
        remapped = {}
        for token, value in bindings.items():
            remapped[by_id.get(value) or token] = value
        bindings = remapped
    has_bindings = bool(bindings)
    current_mentions = node.get('referenceMentions') or {}
    if text != node.get('text', _MISSING) or list(bindings.items()) != list(current_mentions.items() if isinstance(current_mentions, dict) else []):
        node = {**node, 'text': text}
        if text is _MISSING:
            node.pop('text')
        if has_bindings or _truthy(node.get('referenceMentions')):
            node['referenceMentions'] = bindings
    return node


def reconcile_reference_mentions(before, after):
    """reconcileReferenceMentions(before, after) on {'nodes', 'edges'} documents; returns the new node list."""
    before = {'nodes': [n for n in before.get('nodes') or [] if isinstance(n, dict)], 'edges': list(before.get('edges') or [])}
    nodes = [n for n in after.get('nodes') or [] if isinstance(n, dict)]
    after = {'nodes': nodes, 'edges': list(after.get('edges') or [])}
    if _unchanged(before, after):
        return nodes
    previous = {node.get('id'): node for node in before['nodes']}
    return [_reconcile_node(node, before, after, previous) if node.get('type') in GENERATION_TYPES else node
            for node in nodes]
