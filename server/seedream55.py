"""Image-only Seedream 5.5 capability classification; endpoint IDs stay opaque."""
MODEL = 'dola-seedream-5-5-261028'
ALIASES = {MODEL, 'seedream-5.5', 'seedream-5-5', 'dola-seedream-5-5'}
SIZES = {'1:1':'1536x1536','4:3':'1792x1344','3:4':'1344x1792','16:9':'2048x1152','9:16':'1152x2048','3:2':'1872x1248','2:3':'1248x1872','21:9':'2352x1008'}
def enabled(model=None):
    import app
    generation = app.config['generation']
    # Deployment-configured ep- ID of the image model is treated as Seedream 5.5.
    configured = {str(generation['image']['byteplus']['model'] or '')}
    model = str(model if model is not None else app.API_PROVIDERS.get('ark', {}).get('model', ''))
    return model.lower() in ALIASES or (model in configured and model.startswith('ep-'))
