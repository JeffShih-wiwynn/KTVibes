"""Keep page assets and relative module imports on one build-specific URL tree."""
from fastapi.responses import HTMLResponse


def document(runtime, filename):
    source = (runtime.root / 'static' / filename).read_text(encoding='utf-8')
    source = source.replace('/static/', f'/static/{runtime.asset_version}/')
    return HTMLResponse(source, headers={'Cache-Control': 'no-store'})
