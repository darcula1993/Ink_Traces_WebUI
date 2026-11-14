"""Client-facing task serialization without signed Provider URLs.

FIX-B1-20261114: provider result URLs (e.g. TOS/S3 pre-signed links carrying
X-Tos-Credential / X-Tos-Signature) are stored in the task row because the
worker needs them for downloads and billing-boundary evidence.  They must not
be sent to the browser: the UI only needs the local ``/api/tasks/...`` files.

``public_task`` returns a copy of a task dict in which every absolute http(s)
URL inside ``result`` is reduced to ``scheme://host/…`` and URLs embedded in
``error`` text lose their path and query.  Relative local links and ``params``
(user inputs reused by "复用参数") are left untouched.  The stored row is never
modified; download, write-back and cache code keep reading ``tasks.get_task``.
"""
import copy
import re
from urllib.parse import urlsplit

MASK_SUFFIX = '/…'
_URL_IN_TEXT = re.compile(r'https?://[^\s\'"<>()]+', re.IGNORECASE)
# Signed query fragments that may appear without a scheme (e.g. requests' "url: /x?...").
_SIGNED_QUERY = re.compile(
    r'\?[^\s\'"<>]*(?:signature|credential|token|x-tos-|x-amz-|expires|sig=|key=)[^\s\'"<>]*',
    re.IGNORECASE,
)


def mask_url(value):
    """``https://host/path?sig`` -> ``https://host/…``; non-URLs are returned unchanged."""
    if not isinstance(value, str) or not re.match(r'https?://', value, re.IGNORECASE):
        return value
    try:
        parts = urlsplit(value)
        host = parts.hostname or ''
        if parts.port:
            host = f'{host}:{parts.port}'
    except ValueError:
        return '远端结果'
    if not host:
        return '远端结果'
    return f'{parts.scheme.lower()}://{host}{MASK_SUFFIX}'


def mask_text(value):
    if not isinstance(value, str) or not value:
        return value
    masked = _URL_IN_TEXT.sub(lambda match: mask_url(match.group(0)), value)
    return _SIGNED_QUERY.sub('?…', masked)


def _mask_tree(value):
    if isinstance(value, dict):
        return {key: _mask_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_tree(item) for item in value]
    if isinstance(value, str):
        if re.match(r'https?://', value, re.IGNORECASE):
            return mask_url(value)
        # Text fields (e.g. error_details.message) may embed a remote address.
        return _URL_IN_TEXT.sub(lambda match: mask_url(match.group(0)), value)
    return value


def public_task(task):
    """Copy of ``task`` safe to return to the browser (None stays None)."""
    if not task:
        return task
    data = copy.copy(task)
    if isinstance(data.get('result'), (dict, list)):
        data['result'] = _mask_tree(data['result'])
    if data.get('error'):
        data['error'] = mask_text(data['error'])
    return data


def public_tasks(tasks):
    return [public_task(task) for task in tasks]


def public_document(document):
    """Canvas document copy whose node ``task.error`` texts carry no signed URLs.

    FIX-B1 D1: older write-backs stored the raw task error in the canvas
    document; responses mask it without rewriting the stored history.
    """
    if not isinstance(document, dict) or not isinstance(document.get('nodes'), list):
        return document
    nodes = []
    for node in document['nodes']:
        task = node.get('task') if isinstance(node, dict) else None
        if isinstance(task, dict) and isinstance(task.get('error'), str) and task['error']:
            masked = mask_text(task['error'])
            if masked != task['error']:
                node = {**node, 'task': {**task, 'error': masked}}
        nodes.append(node)
    return {**document, 'nodes': nodes}


def public_workflow(workflow):
    if not isinstance(workflow, dict) or 'document' not in workflow:
        return workflow
    return {**workflow, 'document': public_document(workflow['document'])}


# LAYER-SRC-MASK D1: only these Provider address fields are masked in layer
# documents/results.  User content (names, descriptions, OCR text) is never
# rewritten, so a saved document round-trips byte for byte.
LAYER_REMOTE_KEYS = frozenset({'source_url'})
LAYER_REMOTE_LIST_KEYS = frozenset({'source_urls'})
_REMOTE_PLACEHOLDER = '远端结果'


def _mask_layer_container(container):
    """Copy of a layer document/result with only whitelisted remote fields masked."""
    if not isinstance(container, dict):
        return container
    data = dict(container)
    for key in LAYER_REMOTE_KEYS:
        if key in data:
            data[key] = mask_url(data[key])
    for key in LAYER_REMOTE_LIST_KEYS:
        if isinstance(data.get(key), list):
            data[key] = [mask_url(item) for item in data[key]]
    if isinstance(data.get('layers'), list):
        layers = []
        for layer in data['layers']:
            if isinstance(layer, dict):
                layer = dict(layer)
                for key in LAYER_REMOTE_KEYS:
                    if key in layer:
                        layer[key] = mask_url(layer[key])
            layers.append(layer)
        data['layers'] = layers
    return data


def mask_layer_fields(layer):
    """Single layer dict with only whitelisted remote fields masked (zip manifest)."""
    if not isinstance(layer, dict):
        return layer
    return {key: mask_url(value) if key in LAYER_REMOTE_KEYS else value for key, value in layer.items()}


def _public_revision(revision):
    if not isinstance(revision, dict):
        return revision
    data = dict(revision)
    for key in ('result', 'document'):
        if isinstance(data.get(key), dict):
            data[key] = _mask_layer_container(data[key])
    return data


def public_layer_document(document):
    """LAYER-SRC-MASK: layer document copy whose ``layers[].source_url`` is
    reduced to ``scheme://host/…``.  Every other field (local links, names,
    descriptions, OCR text) is returned unchanged."""
    return _mask_layer_container(document)


def public_layer_project(project):
    """FIX-B1 D2 + LAYER-SRC-MASK: layer project with masked ``current_task``,
    ``document`` and revision results/documents."""
    if not isinstance(project, dict):
        return project
    data = dict(project)
    if data.get('current_task'):
        data['current_task'] = public_task(data['current_task'])
    if isinstance(data.get('document'), dict):
        data['document'] = public_layer_document(data['document'])
    if isinstance(data.get('revisions'), list):
        data['revisions'] = [_public_revision(revision) for revision in data['revisions']]
    return data


def _stored_layers(project):
    """All stored layer dicts of a project (current document, revision documents/results)."""
    sources = [(project.get('document') or {}).get('layers')]
    for revision in project.get('revisions') or []:
        if isinstance(revision, dict):
            sources.append((revision.get('document') or {}).get('layers'))
            sources.append((revision.get('result') or {}).get('layers'))
    for layers in sources:
        if isinstance(layers, list):
            for layer in layers:
                if isinstance(layer, dict):
                    yield layer


def _looks_masked(value):
    return value == _REMOTE_PLACEHOLDER or (
        value.endswith(MASK_SUFFIX) and re.match(r'https?://', value, re.IGNORECASE) is not None)


def restore_layer_remote_fields(document, project):
    """LAYER-SRC-MASK: the browser only ever sees masked remote addresses, so a
    saved document would otherwise overwrite stored ``source_url`` values with
    ``https://host/…``.  For each incoming layer matched by ``id`` or
    ``local_url``, a string field equal to the masked form of the stored value
    gets the stored original back.  Unmatched masked values are dropped.
    Only ``LAYER_REMOTE_KEYS`` are touched; all other fields are saved as sent."""
    if not isinstance(document, dict) or not isinstance(document.get('layers'), list):
        return document
    by_id, by_local = {}, {}
    for layer in _stored_layers(project or {}):
        if layer.get('id') is not None:
            by_id.setdefault(str(layer['id']), layer)
        if isinstance(layer.get('local_url'), str) and layer['local_url']:
            by_local.setdefault(layer['local_url'], layer)
    layers = []
    for layer in document['layers']:
        if not isinstance(layer, dict):
            layers.append(layer)
            continue
        stored = by_id.get(str(layer.get('id'))) if layer.get('id') is not None else None
        if stored is None and isinstance(layer.get('local_url'), str):
            stored = by_local.get(layer['local_url'])
        restored = dict(layer)
        for key in LAYER_REMOTE_KEYS:
            value = layer.get(key)
            if not isinstance(value, str):
                continue
            original = (stored or {}).get(key)
            if isinstance(original, str) and original != value and mask_url(original) == value:
                restored[key] = original
            elif original != value and _looks_masked(value):
                restored.pop(key)
        layers.append(restored)
    return {**document, 'layers': layers}
