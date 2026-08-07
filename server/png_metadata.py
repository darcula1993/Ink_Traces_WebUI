"""Build and parse portable PNG generation metadata."""

import json
import math
import re


SCHEMA = 'ink-traces/png-info/v1'
ALLOWED_PARAMS = (
    'aspect_ratio',
    'resolution',
    'size',
    'custom_width',
    'custom_height',
    'output_format',
    'watermark',
    'use_search',
    'think_level',
)


def public_params(params):
    source = params if isinstance(params, dict) else {}
    return {key: source[key] for key in ALLOWED_PARAMS if key in source}


def build_text_entries(prompt, params):
    clean_params = public_params(params)
    payload = {
        'schema': SCHEMA,
        'prompt': str(prompt or ''),
        'params': clean_params,
    }
    readable = [str(prompt or '').strip(), '', 'Generation parameters:']
    readable.extend(f'{key}: {_format_value(value)}' for key, value in clean_params.items())
    return {
        'ink_traces': json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
        'parameters': '\n'.join(readable).strip(),
    }


def parse_text_entries(entries):
    text_entries = {
        str(key): str(value)
        for key, value in (entries or {}).items()
        if isinstance(value, (str, int, float, bool))
    }
    native = _parse_json(text_entries.get('ink_traces'))
    if isinstance(native, dict):
        return {
            'source': 'ink_traces',
            'prompt': str(native.get('prompt') or ''),
            'params': public_params(native.get('params')),
            'chunks': _bounded_chunks(text_entries),
        }

    parameters = text_entries.get('parameters', '')
    parsed_prompt, parsed_params = _parse_parameters_text(parameters)
    return {
        'source': 'parameters' if parameters else 'unknown',
        'prompt': parsed_prompt,
        'params': public_params(parsed_params),
        'chunks': _bounded_chunks(text_entries),
    }


def _parse_json(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _parse_parameters_text(value):
    if not isinstance(value, str) or not value.strip():
        return '', {}
    native = _parse_json(value)
    if isinstance(native, dict):
        return str(native.get('prompt') or ''), native.get('params') or native

    marker = '\nGeneration parameters:\n'
    if marker in value:
        prompt, raw_params = value.split(marker, 1)
        params = {}
        for line in raw_params.splitlines():
            key, separator, raw_value = line.partition(':')
            if separator and key.strip() in ALLOWED_PARAMS:
                params[key.strip()] = _parse_value(raw_value.strip())
        return prompt.strip(), params

    lines = value.strip().splitlines()
    settings_index = next(
        (index for index in range(len(lines) - 1, -1, -1) if re.search(r'(^|,\s*)(Steps|Size|Model):', lines[index])),
        None,
    )
    if settings_index is None:
        return value.strip(), {}
    prompt_lines = lines[:settings_index]
    negative_index = next((index for index, line in enumerate(prompt_lines) if line.startswith('Negative prompt:')), None)
    if negative_index is not None:
        prompt_lines = prompt_lines[:negative_index]
    settings = {}
    for part in re.split(r',\s*(?=[A-Za-z][A-Za-z _-]*:)', lines[settings_index]):
        key, separator, raw_value = part.partition(':')
        if separator:
            settings[key.strip().lower().replace(' ', '_')] = raw_value.strip()
    size = settings.get('size')
    params = {}
    if size and re.fullmatch(r'\d+x\d+', size):
        width, height = (int(number) for number in size.split('x', 1))
        divisor = math.gcd(width, height)
        params['aspect_ratio'] = f'{width // divisor}:{height // divisor}'
    return '\n'.join(prompt_lines).strip(), params


def _parse_value(value):
    lowered = value.lower()
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False
    return value


def _format_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _bounded_chunks(entries, per_chunk=200_000, total=500_000):
    output = {}
    remaining = total
    for key, value in entries.items():
        if remaining <= 0:
            break
        bounded = value[:min(per_chunk, remaining)]
        output[key] = bounded
        remaining -= len(bounded)
    return output
