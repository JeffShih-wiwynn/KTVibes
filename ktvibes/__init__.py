import os
try:
    import certifi
except ModuleNotFoundError as error:
    if error.name != 'certifi':
        raise
    certifi = None

# uv's standalone Python on macOS has no CA bundle, which breaks model and NLTK downloads.
# The Linux dependency installer imports this package before dependencies exist.
if certifi is not None:
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
