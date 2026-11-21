"""Read-only SQLite aggregation of recent task durations (P50 & P25-P75).

V24-W3-STAGE-ETA-20261121 (#13): computes local historical task duration
references over the last 30 days from succeeded tasks with valid ``created_at``
and ``completed_at`` timestamps.

Security & privacy boundaries:
- Read-only queries only; never selects ``prompt``, ``result``, ``error`` or URLs.
- Raw Ark endpoint IDs (``ep-...``) are normalized to model families (or dropped
  to type-level aggregation) and never returned in responses.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import re

import tasks as task_db
from task_public import mask_endpoint_ids

DEFAULT_WINDOW_DAYS = 30
MIN_MODEL_SAMPLES = 2
MAX_VALID_DURATION_SECONDS = 86400.0
KNOWN_TASK_TYPES = ('image', 'video', 'audio', 'layer')

_ENDPOINT_PREFIX_RE = re.compile(r'(?:^|[^a-z0-9])ep-(?:m-)?[0-9]{6,}', re.IGNORECASE)
_SAFE_MODEL_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')


def _parse_iso_utc(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    normalized = text.replace(' ', 'T')
    if normalized.endswith(('Z', 'z')):
        normalized = normalized[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _looks_like_endpoint_id(value):
    if not isinstance(value, str) or not value:
        return False
    if mask_endpoint_ids(value) != value:
        return True
    lower = value.lower()
    if lower.startswith('ep-') or _ENDPOINT_PREFIX_RE.search(lower):
        return True
    return False


def _parse_params(raw_params):
    if isinstance(raw_params, dict):
        return raw_params
    if isinstance(raw_params, str) and raw_params.strip():
        try:
            loaded = json.loads(raw_params)
            if isinstance(loaded, dict):
                return loaded
        except ValueError:
            return {}
    return {}


def normalize_model_family(task_type, params=None, provider=None):
    """Map task model metadata to a safe model family string (never returns ``ep-...``)."""
    parsed = _parse_params(params)
    raw_model = str(parsed.get('model') or '').strip()
    cost_est = parsed.get('cost_estimate')
    cost_model = str(cost_est.get('model') or '').strip() if isinstance(cost_est, dict) else ''
    seedream55 = bool(parsed.get('seedream55'))
    lower = raw_model.lower()
    cost_lower = cost_model.lower()

    if task_type in ('image', 'layer'):
        if seedream55 or '5-5' in lower or '5.5' in lower or cost_lower == 'seedream-5.5':
            return 'seedream-5.5'
        if (
            '5-0' in lower
            or '5.0' in lower
            or 'seedream' in lower
            or cost_lower == 'seedream-5.0-pro'
            or _looks_like_endpoint_id(raw_model)
            or not raw_model
        ):
            return 'seedream-5.0-pro'

    elif task_type == 'video':
        if '2.5-moderated' in lower or '2-5-moderated' in lower:
            return 'seedance-2.5-moderated'
        if 'seedance-2.5' in lower or 'seedance-2-5' in lower or '2.5' in lower or cost_lower == 'seedance-2.5':
            return 'seedance-2.5'
        if 'seedance-2.0' in lower or 'seedance-2-0' in lower or '2.0' in lower or cost_lower == 'seedance-2.0':
            return 'seedance-2.0'
        if _looks_like_endpoint_id(raw_model) or not raw_model:
            return None

    elif task_type == 'audio':
        if 'seed-audio' in lower or 'audio-1.0' in lower or 'audio-1-0' in lower or (
            not raw_model and str(provider or '').lower() == 'cupsy'
        ):
            return 'seed-audio-1.0'
        if _looks_like_endpoint_id(raw_model) or not raw_model:
            return None

    if not raw_model or _looks_like_endpoint_id(raw_model) or '://' in raw_model:
        return None
    if _SAFE_MODEL_SLUG_RE.fullmatch(lower):
        return lower
    return None


def _percentile(sorted_values, pct):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(float(sorted_values[0]), 1)
    pos = (len(sorted_values) - 1) * (float(pct) / 100.0)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    value = sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac
    return round(float(value), 1)


def _summarize(durations):
    if not durations:
        return None
    ordered = sorted(durations)
    return {
        'sample_count': len(ordered),
        'p25_seconds': _percentile(ordered, 25),
        'p50_seconds': _percentile(ordered, 50),
        'p75_seconds': _percentile(ordered, 75),
    }


def compute_duration_stats(window_days=DEFAULT_WINDOW_DAYS, task_type=None, model=None, now=None):
    """Aggregate recent succeeded task durations by type and normalized model family."""
    days = max(1, min(int(window_days or DEFAULT_WINDOW_DAYS), 90))
    anchor = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    else:
        anchor = anchor.astimezone(timezone.utc)
    cutoff = anchor - timedelta(days=days)
    # Subtract a small buffer for SQL string pre-filtering across timezone offsets,
    # then filter strictly in Python with parsed UTC datetimes.
    sql_cutoff = (cutoff - timedelta(days=1)).isoformat()

    query = '''
        SELECT type, provider, params, created_at, completed_at
        FROM tasks
        WHERE status = 'succeeded'
          AND deleted_at IS NULL
          AND created_at IS NOT NULL
          AND completed_at IS NOT NULL
          AND created_at >= ?
    '''
    query_params = [sql_cutoff]
    if task_type:
        query += ' AND type = ?'
        query_params.append(task_type)

    rows = task_db.get_db().execute(query, query_params).fetchall()

    by_type_values = {}
    by_model_values = {}
    for row in rows:
        created_dt = _parse_iso_utc(row['created_at'])
        completed_dt = _parse_iso_utc(row['completed_at'])
        if created_dt is None or completed_dt is None:
            continue
        if created_dt < cutoff or created_dt > anchor:
            continue
        duration = (completed_dt - created_dt).total_seconds()
        if not math.isfinite(duration) or duration < 0 or duration > MAX_VALID_DURATION_SECONDS:
            continue
        row_type = str(row['type'] or '').strip().lower()
        if not row_type:
            continue
        by_type_values.setdefault(row_type, []).append(duration)
        family = normalize_model_family(row_type, row['params'], row['provider'])
        if family:
            by_model_values.setdefault((row_type, family), []).append(duration)

    types_to_report = (task_type,) if task_type else KNOWN_TASK_TYPES
    by_type = {t: _summarize(by_type_values.get(t, [])) for t in types_to_report}
    for extra_type, values in by_type_values.items():
        if extra_type not in by_type:
            by_type[extra_type] = _summarize(values)

    by_model = {}
    for (row_type, family), values in sorted(by_model_values.items()):
        if len(values) < MIN_MODEL_SAMPLES:
            continue
        summary = _summarize(values)
        if summary is not None:
            by_model[f'{row_type}:{family}'] = {
                'type': row_type,
                'model': family,
                **summary,
            }

    stat = None
    if task_type:
        normalized_query_model = (
            normalize_model_family(task_type, {'model': model}) if model else None
        )
        if normalized_query_model and f'{task_type}:{normalized_query_model}' in by_model:
            stat = {**by_model[f'{task_type}:{normalized_query_model}'], 'scope': 'model'}
        elif by_type.get(task_type) is not None:
            stat = {
                'type': task_type,
                'model': None,
                'scope': 'type',
                **by_type[task_type],
            }

    return {
        'window_days': days,
        'by_type': by_type,
        'by_model': by_model,
        'stat': stat,
    }
