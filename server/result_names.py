"""Display/download names for generated results: <node name>_<task id>[_N].<ext>.

Only the display and download name change; files on disk keep their names.
Tasks without a stored result_name (legacy or non-canvas) keep old behaviour.
"""
import json
import os
import re

MAX_STEM = 80
_BAD = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')
# Unicode bidirectional controls (LRM/RLM/ALM, embeddings/overrides, isolates) can disguise
# an extension such as "abc\u202Egnp.exe"; they are removed outright.
_BIDI = re.compile('[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]')
# Windows reserved device names, matched case-insensitively on the part before the first dot.
_WINDOWS_RESERVED = re.compile(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', re.IGNORECASE)


def _safe_windows_stem(text):
    if _WINDOWS_RESERVED.fullmatch(text.split('.', 1)[0].rstrip(' ')):
        return f'_{text}'
    return text


def clean_result_name(value):
    """Sanitise a node name: no separators/control chars, bounded length, CJK kept."""
    if not isinstance(value, str):
        return ''
    text = _BIDI.sub('', value)
    text = _BAD.sub(' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' .')
    return _safe_windows_stem(text[:MAX_STEM].strip(' .'))[:MAX_STEM].rstrip(' .')


def _output_index(filename):
    match = re.search(r'_(\d+)(?:\.[^.]+)?$', filename)
    return int(match.group(1)) if match else 0


def result_display_name(result_name, task_id, filename, suffix=''):
    stem = clean_result_name(result_name)
    if not stem:
        return None
    index = _output_index(os.path.basename(filename))
    extension = os.path.splitext(filename)[1].lower()
    if extension == '.jpeg':
        extension = '.jpg'
    seq = f'_{index + 1}' if index > 0 else ''
    return f'{stem}_{task_id}{seq}{suffix}{extension}'


def task_result_name(params):
    if isinstance(params, str):
        try:
            params = json.loads(params or '{}')
        except ValueError:
            return ''
    return clean_result_name((params or {}).get('result_name')) if isinstance(params, dict) else ''


def content_disposition(disposition, name):
    from urllib.parse import quote
    if re.fullmatch(r'[\x20-\x7e]+', name) and '"' not in name:
        return f'{disposition}; filename="{name}"'
    ascii_name = re.sub(r'[^\x20-\x7e]', '_', name).replace('"', '')
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name, safe="")}'
