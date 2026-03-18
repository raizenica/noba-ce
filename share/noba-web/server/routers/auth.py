# share/noba-web/server/routers/auth.py
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from ..security import verify_password, create_access_token, rate_limiter

router = APIRouter()

# In production, this would query a users.db file or load from your config.yaml.
# For now, this is 'admin' with the password 'admin' (hashed securely via bcrypt)
MOCK_USER_DB = {
    "admin": "$2a$12$D24Xj8bI0jAovD88Q6zD5eA/RkI.P1E5J6b6X7ZpG2tV4xL9f3H3G"
}

class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
async def login(request: Request, credentials: LoginRequest):
    # CRITICAL: Strict rate limiting to prevent password guessing
    rate_limiter(request, limit=5, window=60)

    hashed_pw = MOCK_USER_DB.get(credentials.username)
    if not hashed_pw or not verify_password(credentials.password, hashed_pw):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": credentials.username})
    return {"access_token": access_token, "token_type": "bearer"}
