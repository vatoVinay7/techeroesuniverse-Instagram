"""Encrypted storage of the Instagram access token inside the (public) repository.

Why: long-lived Instagram tokens expire after 60 days and must be refreshed.
GitHub Actions cannot rewrite its own secrets with the default GITHUB_TOKEN, so the
refreshed token is stored encrypted in state/token.enc.json. The key (IG_TOKEN_KEY)
lives only in GitHub Secrets.

Seed logic: the secret IG_ACCESS_TOKEN is the "seed". If the seed changes (Vinay
generated a new token by hand), the new seed wins over the stored token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import TOKEN_PATH
from .statefile import read_json, write_json

FORMAT_VERSION = 1
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 1
REFRESH_AFTER = timedelta(days=7)      # refresh weekly; Meta allows refresh after 24 h
MIN_AGE_FOR_REFRESH = timedelta(hours=24)
WARN_BEFORE_EXPIRY = timedelta(days=10)


class TokenError(RuntimeError):
    pass


@dataclass
class TokenRecord:
    token: str
    seed_hash: str
    obtained_at: str            # when this token value was issued/stored (UTC ISO)
    expires_at: str | None      # UTC ISO, None if unknown

    def obtained(self) -> datetime:
        return datetime.fromisoformat(self.obtained_at)

    def expires(self) -> datetime | None:
        return datetime.fromisoformat(self.expires_at) if self.expires_at else None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 24:
        raise TokenError("IG_TOKEN_KEY ist zu kurz (mind. 24 Zeichen)")
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                          p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024)


def encrypt_record(record: TokenRecord, passphrase: str) -> dict:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(passphrase, salt)
    plaintext = json.dumps(asdict(record)).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, b"igpost-token-v1")
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"version": FORMAT_VERSION, "salt": b64(salt), "nonce": b64(nonce), "ciphertext": b64(ciphertext)}


def decrypt_record(blob: dict, passphrase: str) -> TokenRecord:
    if blob.get("version") != FORMAT_VERSION:
        raise TokenError(f"Unbekanntes Token-Dateiformat: {blob.get('version')}")
    d = lambda k: base64.b64decode(blob[k])  # noqa: E731
    key = _derive_key(passphrase, d("salt"))
    try:
        plaintext = AESGCM(key).decrypt(d("nonce"), d("ciphertext"), b"igpost-token-v1")
    except InvalidTag as exc:
        raise TokenError("Token-Datei lässt sich nicht entschlüsseln (falscher IG_TOKEN_KEY?)") from exc
    return TokenRecord(**json.loads(plaintext))


class TokenStore:
    def __init__(self, *, seed: str | None, passphrase: str | None, path: Path = TOKEN_PATH):
        self.seed = (seed or "").strip()
        self.passphrase = (passphrase or "").strip()
        self.path = path
        if not self.passphrase:
            raise TokenError("Secret IG_TOKEN_KEY fehlt")

    @classmethod
    def from_env(cls) -> "TokenStore":
        return cls(seed=os.environ.get("IG_ACCESS_TOKEN"), passphrase=os.environ.get("IG_TOKEN_KEY"))

    def load(self) -> TokenRecord:
        """Return the token to use; reseed from the secret if it changed."""
        stored: TokenRecord | None = None
        blob = read_json(self.path, None)
        if blob:
            try:
                stored = decrypt_record(blob, self.passphrase)
            except TokenError:
                if not self.seed:
                    raise
                # Schlüssel wurde geändert: gespeicherten Token verwerfen, mit dem Secret neu starten
                stored = None

        if self.seed and (stored is None or stored.seed_hash != _hash(self.seed)):
            record = TokenRecord(token=self.seed, seed_hash=_hash(self.seed),
                                 obtained_at=_now().isoformat(), expires_at=None)
            self.save(record)
            return record
        if stored is None:
            raise TokenError("Kein Instagram-Token vorhanden – Secret IG_ACCESS_TOKEN setzen")
        return stored

    def save(self, record: TokenRecord) -> None:
        write_json(self.path, encrypt_record(record, self.passphrase))

    def needs_refresh(self, record: TokenRecord, now: datetime | None = None) -> bool:
        now = now or _now()
        age = now - record.obtained()
        if age < MIN_AGE_FOR_REFRESH:
            return False
        expires = record.expires()
        if expires is None:
            return True
        return age >= REFRESH_AFTER or expires - now <= WARN_BEFORE_EXPIRY

    def apply_refresh(self, record: TokenRecord, response: dict, now: datetime | None = None) -> TokenRecord:
        now = now or _now()
        expires_in = int(response.get("expires_in") or 0)
        new = TokenRecord(
            token=response["access_token"],
            seed_hash=record.seed_hash,
            obtained_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=expires_in)).isoformat() if expires_in else None,
        )
        self.save(new)
        return new


def _now() -> datetime:
    return datetime.now(timezone.utc)
