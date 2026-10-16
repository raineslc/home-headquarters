"""Minimal Web Push sender (RFC 8291 message encryption, RFC 8292 VAPID) on `cryptography`.

The browser's push service (for Chrome on Android, Google's) relays the encrypted message to
the phone; only the phone can read it. The private key lives in Secret Manager
(WEB_PUSH_PRIVATE_KEY, PEM); the matching public key is derived from it.
"""
import base64
import json
import os
import struct
import time
from urllib.parse import urlsplit
import requests
from cryptography.hazmat.primitives import hashes, hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

RECORD_SIZE = 4096
# Endpoints come from the browser, so only the major browsers' push services are accepted;
# the server never posts to any other address.
PUSH_HOSTS = ('fcm.googleapis.com', 'updates.push.services.mozilla.com', '.push.apple.com', '.notify.windows.com')

def allowed_endpoint(endpoint):
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    parts = urlsplit(endpoint)
    host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and parts.port in (None, 443) and not parts.username and \
        any(host == name or (name.startswith('.') and host.endswith(name)) for name in PUSH_HOSTS)

class PushError(Exception):
    def __init__(self, message, gone=False):
        super().__init__(message)
        self.gone = gone  # the subscription no longer exists and should be removed

def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))

def private_key():
    pem = settings.WEB_PUSH_PRIVATE_KEY.replace('\\n', '\n').strip()
    if not pem:
        return None
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != 'secp256r1':
        raise ValueError('WEB_PUSH_PRIVATE_KEY must be a P-256 key.')
    return key

def raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

def public_key():
    """The application server key browsers need to subscribe, or '' when push is not set up."""
    key = private_key()
    return b64(raw_public(key)) if key else ''

def hmac_sha256(key, data):
    mac = hmac.HMAC(key, hashes.SHA256())
    mac.update(data)
    return mac.finalize()

def encrypt(payload, p256dh, auth, salt=None, server_key=None):
    """Encrypt one message for one subscription (aes128gcm, single record)."""
    ua_public = unb64(p256dh)
    auth_secret = unb64(auth)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = raw_public(server_key)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    prk_key = hmac_sha256(auth_secret, shared)
    ikm = hmac_sha256(prk_key, b'WebPush: info\x00' + ua_public + as_public + b'\x01')
    salt = salt or os.urandom(16)
    prk = hmac_sha256(salt, ikm)
    cek = hmac_sha256(prk, b'Content-Encoding: aes128gcm\x00\x01')[:16]
    nonce = hmac_sha256(prk, b'Content-Encoding: nonce\x00\x01')[:12]
    body = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)
    return salt + struct.pack('!IB', RECORD_SIZE, len(as_public)) + as_public + body

def vapid_header(endpoint, key):
    parts = urlsplit(endpoint)
    claims = {'aud': f'{parts.scheme}://{parts.netloc}', 'exp': int(time.time()) + 12 * 3600,
              'sub': settings.WEB_PUSH_CONTACT}
    signing_input = b64(json.dumps({'typ': 'JWT', 'alg': 'ES256'}).encode()) + '.' + b64(json.dumps(claims).encode())
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing_input + '.' + b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return f'vapid t={token}, k={b64(raw_public(key))}'

def send(subscription, message, ttl=3600):
    """Send a JSON message to a PushSubscription. Raises PushError on failure."""
    key = private_key()
    if key is None:
        raise PushError('Phone reminders are not set up on the server.')
    if not allowed_endpoint(subscription.endpoint):
        raise PushError('Unsupported push service.', gone=True)
    body = encrypt(json.dumps(message).encode(), subscription.p256dh, subscription.auth)
    headers = {'Authorization': vapid_header(subscription.endpoint, key), 'Content-Encoding': 'aes128gcm',
               'Content-Type': 'application/octet-stream', 'TTL': str(ttl), 'Urgency': 'high'}
    try:
        response = requests.post(subscription.endpoint, data=body, headers=headers, timeout=10)
    except requests.RequestException as error:
        raise PushError(f'Push service unreachable ({type(error).__name__}).')
    if response.status_code in (404, 410):
        raise PushError('This device turned off reminders.', gone=True)
    if response.status_code >= 300:
        raise PushError(f'Push service answered {response.status_code}.')
