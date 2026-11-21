"""Image-only Seedream 5.5 capability classification; endpoint IDs stay opaque."""
MODEL = 'dola-seedream-5-5-261028'
MODEL_50_PRO = 'seedream-5-0-pro'
ALIASES = {MODEL, 'seedream-5.5', 'seedream-5-5', 'dola-seedream-5-5'}
PRO_ALIASES = {MODEL_50_PRO, 'seedream-5.0-pro'}
DECLARED_CAPABILITY_MODELS = {'', MODEL, MODEL_50_PRO}
SIZES = {'1:1':'1536x1536','4:3':'1792x1344','3:4':'1344x1792','16:9':'2048x1152','9:16':'1152x2048','3:2':'1872x1248','2:3':'1248x1872','21:9':'2352x1008'}


def _resolve_declared(declared):
    text = str(declared or '').strip().lower()
    if not text:
        return None
    if text in ALIASES:
        return True
    if text in PRO_ALIASES:
        return False
    return None


def _auto_enabled(model_str):
    import app
    generation = app.config['generation']
    # Deployment-configured ep- ID of the image model is treated as Seedream 5.5.
    configured = {str(generation['image']['byteplus']['model'] or '')}
    return model_str.lower() in ALIASES or (model_str in configured and model_str.startswith('ep-'))


def enabled(model=None, capability_model=None):
    explicit = _resolve_declared(capability_model)
    if explicit is not None:
        return explicit
    import app
    import profile_runtime
    profile = profile_runtime.current_profile()
    if profile and profile.get('kind') == 'image' and profile.get('adapter') == 'ark':
        settings = profile.get('settings') or {}
        declared = _resolve_declared(settings.get('capability_model'))
        raw_profile_model = str(settings.get('model') or '')
        effective_profile_model = raw_profile_model or MODEL_50_PRO
        if declared is not None and (model is None or str(model) in (raw_profile_model, effective_profile_model)):
            return declared
    ark_cfg = app.API_PROVIDERS.get('ark', {})
    ark_model = str(ark_cfg.get('model', '') or '')
    ark_declared = _resolve_declared(ark_cfg.get('capability_model'))
    if ark_declared is not None and (model is None or str(model) in (ark_model, ark_model or MODEL_50_PRO)):
        return ark_declared
    effective = str(model if model is not None else ark_model)
    return _auto_enabled(effective)


def capability_model(model=None, declared=None):
    resolved = _resolve_declared(declared)
    if resolved is True:
        return MODEL
    if resolved is False:
        return MODEL_50_PRO
    if declared is not None:
        effective = str(model or '') or MODEL_50_PRO
        return MODEL if _auto_enabled(effective) else effective
    import app
    effective = str(model if model is not None else app.API_PROVIDERS.get('ark', {}).get('model', '')) or MODEL_50_PRO
    return MODEL if enabled(effective) else effective
