"""Optional external access, with credentials scoped to one server run."""
import asyncio
import hashlib
import hmac
import os
import secrets
import time
from collections import OrderedDict, deque
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from .assets import document
from pydantic import BaseModel, Field

COOKIE = 'ktvibes_session'
ITERATIONS = 600_000


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2-sha256${ITERATIONS}${salt}${digest}'


def validate_external(url: str, encoded: str) -> str:
    parsed = urlsplit(url)
    parsed.port  # Reject malformed or out-of-range ports before accepting the address.
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/', '/remote'):
        raise ValueError('External address must be an HTTPS address, optionally ending in /remote.')
    algorithm, rounds, salt, digest = encoded.split('$')
    if algorithm != 'pbkdf2-sha256' or int(rounds) != ITERATIONS or len(bytes.fromhex(salt)) != 16 or len(bytes.fromhex(digest)) != 32:
        raise ValueError('A valid password hash is required for external access.')
    return f'https://{parsed.netloc}/remote'


class Access:
    def __init__(self):
        self.enabled = os.environ.get('KTVIBES_EXTERNAL_ENABLED') == '1'
        self.encoded = os.environ.get('KTVIBES_PASSWORD_HASH', '') if self.enabled else ''
        self.external_url = validate_external(os.environ.get('KTVIBES_REMOTE_URL', ''), self.encoded) if self.enabled else ''
        self.credential_type = os.environ.get('KTVIBES_CREDENTIAL_TYPE', 'password')
        if self.credential_type not in ('pin', 'password'):
            raise ValueError('Unknown credential type')
        self.key = secrets.token_urlsafe(32) if self.enabled else None
        self.secret = secrets.token_bytes(32)
        self.desktop = os.environ.get('KTVIBES_DESKTOP_TOKEN', '')
        self.failures = OrderedDict()
        self.attempts = deque()
        self.lock = asyncio.Lock()

    def scope(self, request):
        token = request.cookies.get(COOKIE, '')
        parts = token.split('.')
        if len(token) < 200 and len(parts) == 3 and parts[0] in ('owner', 'remote') and len(parts[2]) == 64 and all(c in '0123456789abcdef' for c in parts[2]):
            payload = '.'.join(parts[:2])
            if hmac.compare_digest(parts[2], hmac.new(self.secret, payload.encode(), 'sha256').hexdigest()):
                return parts[0]
        return None

    def session(self, scope):
        payload = scope + '.' + secrets.token_urlsafe(24)
        return payload + '.' + hmac.new(self.secret, payload.encode(), 'sha256').hexdigest()

    def origin_ok(self, request):
        origin = request.headers.get('origin')
        if not origin:
            return request.scope['type'] != 'websocket'
        local = str(request.base_url).rstrip('/').replace('ws://', 'http://', 1).replace('wss://', 'https://', 1)
        external = 'https://' + urlsplit(self.external_url).netloc if self.enabled else ''
        return origin in (local, external)

    def desktop_ok(self, request):
        return bool(self.desktop) and hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Bearer ' + self.desktop).encode())

    async def middleware(self, request, call_next):
        if not self.enabled:
            return await call_next(request)
        path = request.url.path
        public = path.startswith('/static/') and not path.endswith('.html') or path in ('/api/auth/login', '/api/auth/pair', '/api/auth/status')
        scope = self.scope(request)
        desktop = path == '/api/config' and self.desktop_ok(request)
        owner_only = path in ('/', '/tv', '/api/qr.svg', '/api/invite', '/static/tv.html')
        if not public and not desktop and (not scope or owner_only and scope != 'owner'):
            if path in ('/', '/tv', '/remote', '/static/tv.html', '/static/remote.html'):
                response = document(request.app.state.runtime, 'login.html')
            else:
                response = JSONResponse({'detail': 'Sign in to continue.'}, status_code=401)
        elif request.method not in ('GET', 'HEAD', 'OPTIONS') and not self.origin_ok(request):
            response = JSONResponse({'detail': 'Invalid request origin.'}, status_code=403)
        else:
            response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def router(self):
        router = APIRouter()

        @router.get('/api/auth/status')
        async def status(request: Request):
            return {'enabled': self.enabled, 'scope': self.scope(request), 'credential_type': self.credential_type}

        def grant(request, scope):
            response = JSONResponse({'ok': True})
            external_host = urlsplit(self.external_url).hostname
            secure = request.url.scheme == 'https' or bool(external_host and request.url.hostname == external_host)
            response.set_cookie(COOKIE, self.session(scope), httponly=True, secure=secure, samesite='strict', path='/')
            return response

        @router.post('/api/auth/login')
        async def login(body: Password, request: Request):
            if not self.enabled:
                return {'ok': True}
            if self.credential_type == 'pin' and (len(body.password) < 6 or not body.password.isascii() or not body.password.isdigit()):
                raise HTTPException(400, 'Enter a PIN of at least 6 digits.')
            ip = request.client.host if request.client else 'unknown'
            now = time.monotonic()
            async with self.lock:
                recent = [t for t in self.failures.get(ip, []) if t > now - 60]
                while self.attempts and self.attempts[0] < now - 60:
                    self.attempts.popleft()
                if len(recent) >= 5 or len(self.attempts) >= 30:
                    raise HTTPException(429, 'Too many attempts. Please wait one minute.', headers={'Retry-After': '60'})
                self.attempts.append(now)
                _, rounds, salt, expected = self.encoded.split('$')
                actual = await asyncio.to_thread(hashlib.pbkdf2_hmac, 'sha256', body.password.encode(), bytes.fromhex(salt), int(rounds))
                if not hmac.compare_digest(actual.hex(), expected):
                    self.failures[ip] = recent + [now]
                    self.failures.move_to_end(ip)
                    while len(self.failures) > 1024:
                        self.failures.popitem(last=False)
                    raise HTTPException(401, 'Incorrect PIN.' if self.credential_type == 'pin' else 'Incorrect password.')
                self.failures.pop(ip, None)
            return grant(request, 'owner')

        @router.post('/api/auth/pair')
        async def pair(body: Pair, request: Request):
            if not self.enabled:
                return {'ok': True}
            if not hmac.compare_digest(body.key.encode(), self.key.encode()):
                raise HTTPException(401, 'This QR code has expired. Scan the current Player QR code.')
            return grant(request, self.scope(request) or 'remote')

        return router


class Password(BaseModel):
    password: str = Field(max_length=1024)


class Pair(BaseModel):
    key: str = Field(max_length=128)
