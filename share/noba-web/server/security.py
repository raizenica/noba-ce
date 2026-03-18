# share/noba-web/server/security.py
import time
import jwt
from typing import Optional
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# In-memory sliding window rate limiter
RATE_LIMIT_DB = {}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = time.time() + (settings.access_token_expire_minutes * 60)
    to_encode.update({"exp": expire})
    # Use the Pydantic SecretStr safely
    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token credentials")

def rate_limiter(request: Request, limit: int = 10, window: int = 60):
    """
    Protects endpoints by tracking requests per IP within a time window.
    """
    client_ip = request.client.host
    now = time.time()

    if client_ip not in RATE_LIMIT_DB:
        RATE_LIMIT_DB[client_ip] = []

    # Purge requests older than the sliding window
    RATE_LIMIT_DB[client_ip] = [
        req_time for req_time in RATE_LIMIT_DB[client_ip]
        if now - req_time < window
    ]

    if len(RATE_LIMIT_DB[client_ip]) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Circuit breaker triggered."
        )

    RATE_LIMIT_DB[client_ip].append(now)
