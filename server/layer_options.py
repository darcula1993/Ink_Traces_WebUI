"""Seedream layer options are frozen at queue time, never inferred for old tasks."""
import json
import math
import seedream55


def options(data, model):
    modern = seedream55.enabled(model)
    if not modern:
        if any(key in data for key in ('max_images', 'text_recognition')):
            raise ValueError('当前图层模型不支持最大输出数或OCR选项')
        return {}
    count = data.get('max_images', 30)
    if isinstance(count, str) and count.isdecimal():
        count = int(count)
    if type(count) is not int or not 2 <= count <= 100:
        raise ValueError('最大输出数须为2–100的整数（包含底图）')
    recognize = data.get('text_recognition', False)
    if isinstance(recognize, str) and recognize.lower() in ('true', 'false'):
        recognize = recognize.lower() == 'true'
    if type(recognize) is not bool:
        raise ValueError('文字识别选项必须为布尔值')
    return {'max_images': count, 'text_recognition': recognize}


def recognition(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get('text', ''), str) or not isinstance(value.get('lines', []), list):
        raise ValueError('Provider返回的OCR结构无效')
    for line in value.get('lines', []):
        if not isinstance(line, dict) or not isinstance(line.get('runs', []), list):
            raise ValueError('Provider返回的OCR行结构无效')
        if 'bounding_box' in line:
            box = line['bounding_box']
            if not isinstance(box, dict):
                raise ValueError('Provider返回的OCR坐标结构无效')
            for key in ('absolute', 'normalized'):
                if key in box and (not isinstance(box[key], list) or len(box[key]) != 4 or
                                   any(type(n) not in (int, float) or not math.isfinite(n) for n in box[key])):
                    raise ValueError('Provider返回的OCR坐标无效')
        for run in line.get('runs', []):
            if not isinstance(run, dict) or not isinstance(run.get('text', ''), str) or not isinstance(run.get('style', {}), dict):
                raise ValueError('Provider返回的OCR样式段结构无效')
            style = run.get('style', {})
            for key in ('bold', 'italic', 'underline', 'strikethrough', 'shadow', 'translucent'):
                if key in style and type(style[key]) is not bool:
                    raise ValueError('Provider返回的OCR样式开关无效')
            for key in ('similar_font_family', 'foreground_color'):
                if key in style and not isinstance(style[key], str):
                    raise ValueError('Provider返回的OCR样式文字无效')
    if len(json.dumps(value, ensure_ascii=False).encode()) > 1024 * 1024:
        raise ValueError('单层OCR元数据超过1MB限制')
    return value
