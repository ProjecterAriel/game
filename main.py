import os, base64, uuid, time
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import httpx
from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from pymongo import AsyncMongoClient
from pwdlib import PasswordHash

APP_NAME = "AeroWorld"
MONGO_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("MONGODB_DB", "aeroworld")
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()
app = FastAPI(title=APP_NAME, version="0.1.0")
client = AsyncMongoClient(MONGO_URI) if MONGO_URI else None
db = client[DB_NAME] if client else None
online: dict[str, dict] = {}
sockets: dict[str, WebSocket] = {}

@app.on_event("startup")
async def startup():
    if db is not None:
        await db.users.create_index("email", unique=True)
        await db.users.create_index("nickname", unique=True)
        await db.messages.create_index([("user_id", 1), ("created_at", -1)])
        await db.positions.create_index("updated_at")

@app.on_event("shutdown")
async def shutdown():
    if client:
        await client.close()

def require_config():
    if db is None:
        raise HTTPException(503, "MongoDB is not configured. Set MONGODB_URI.")
    if not JWT_SECRET:
        raise HTTPException(503, "JWT_SECRET is not configured.")
    return db

class RegisterData(BaseModel):
    nickname: str = Field(min_length=3, max_length=24)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    avatar: Optional[str] = None

class LoginData(BaseModel):
    email: EmailStr
    password: str

class SettingsData(BaseModel):
    aircraft: Optional[str] = None
    earth_mode: Optional[str] = None
    overlay_opacity: Optional[float] = Field(default=None, ge=0, le=1)

class PositionData(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    altitude: float = Field(default=1000, ge=0, le=100000)
    heading: float = Field(default=0, ge=0, le=360)
    aircraft: Optional[str] = "a320"
    route: Optional[list] = None

class ChatData(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    image: bool = False

def make_token(user_id: str):
    if not JWT_SECRET:
        raise HTTPException(503, "JWT_SECRET is not configured.")
    return jwt.encode({"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=30)}, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def current_user(authorization: str = Header(default="")):
    require_config()
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    try:
        payload = jwt.decode(authorization[7:], JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"_id": payload["sub"]})
    except Exception:
        user = None
    if not user:
        raise HTTPException(401, "Invalid or expired session")
    return user

def public_user(user):
    return {"id": user["_id"], "nickname": user["nickname"], "email": user["email"],
            "avatar": user.get("avatar"), "settings": user.get("settings", {})}

@app.get("/health")
async def health():
    state = "not_configured"
    if db is not None:
        try:
            await db.command("ping")
            state = "connected"
        except Exception:
            state = "error"
    return {"ok": state == "connected", "service": "aeroworld", "database": state}

@app.post("/api/auth/register")
async def register(data: RegisterData):
    require_config()
    nickname = data.nickname.strip()
    email = str(data.email).lower()
    if not nickname:
        raise HTTPException(400, "Nickname is required")
    if await db.users.find_one({"$or": [{"email": email}, {"nickname": nickname}]}):
        raise HTTPException(409, "Email or nickname is already registered")
    avatar = data.avatar
    if avatar and len(avatar) > 1_500_000:
        raise HTTPException(413, "Avatar is too large")
    user = {"_id": str(uuid.uuid4()), "nickname": nickname, "email": email,
            "password_hash": password_hash.hash(data.password), "avatar": avatar,
            "settings": {"aircraft": "a320", "earth_mode": "satellite", "overlay_opacity": 0.72},
            "created_at": datetime.now(timezone.utc)}
    await db.users.insert_one(user)
    return {"token": make_token(user["_id"]), "user": public_user(user)}

@app.post("/api/auth/login")
async def login(data: LoginData):
    require_config()
    user = await db.users.find_one({"email": str(data.email).lower()})
    if not user or not password_hash.verify(data.password, user["password_hash"]):
        raise HTTPException(401, "Incorrect email or password")
    return {"token": make_token(user["_id"]), "user": public_user(user)}

@app.get("/api/auth/me")
async def me(user=Depends(current_user)):
    return {"user": public_user(user)}

@app.patch("/api/user/settings")
async def save_settings(data: SettingsData, user=Depends(current_user)):
    changes = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    if changes:
        await db.users.update_one({"_id": user["_id"]}, {"$set": {f"settings.{k}": v for k, v in changes.items()}})
    updated = await db.users.find_one({"_id": user["_id"]})
    return {"settings": updated.get("settings", {})}

@app.post("/api/flight/position")
async def update_position(data: PositionData, user=Depends(current_user)):
    now = datetime.now(timezone.utc)
    position = {"user_id": user["_id"], "nickname": user["nickname"], "avatar": user.get("avatar"),
                **data.model_dump(), "updated_at": now}
    await db.positions.update_one({"user_id": user["_id"]}, {"$set": position}, upsert=True)
    return {"ok": True, "updated_at": now.isoformat()}

@app.get("/api/online")
async def get_online(user=Depends(current_user)):
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=45)
    cursor = db.positions.find({"updated_at": {"$gte": cutoff}}, {"_id": 0})
    return {"players": await cursor.to_list(length=500)}

@app.post("/api/ai/chat")
async def ai_chat(data: ChatData, user=Depends(current_user)):
    require_config()
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(503, "Set GROQ_API_KEY in Render environment")
    if data.image:
        account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        key = os.getenv("CLOUDFLARE_API_TOKEN")
        model = os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
        if not account or not key:
            raise HTTPException(503, "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN")
        url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
        async with httpx.AsyncClient(timeout=120) as http:
            response = await http.post(url, headers={"Authorization": f"Bearer {key}"}, json={"prompt": data.text})
        if response.status_code >= 400:
            raise HTTPException(502, "Cloudflare image generation failed")
        image_bytes = response.content
        answer = "Image generated."
        image_data = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    else:
        async with httpx.AsyncClient(timeout=90) as http:
            response = await http.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
                json={"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                      "messages": [{"role": "system", "content": "You are AeroWorld copilot. Be helpful, concise, and aviation-aware."},
                                   {"role": "user", "content": data.text}], "temperature": 0.7})
        if response.status_code >= 400:
            raise HTTPException(502, "Groq request failed: " + response.text[:300])
        answer = response.json()["choices"][0]["message"]["content"]
        image_data = None
    item = {"user_id": user["_id"], "prompt": data.text, "answer": answer,
            "image": image_data, "created_at": datetime.now(timezone.utc)}
    await db.messages.insert_one(item)
    return {"answer": answer, "image": image_data}

@app.get("/api/ai/history")
async def ai_history(user=Depends(current_user)):
    cursor = db.messages.find({"user_id": user["_id"]}, {"_id": 0}).sort("created_at", -1).limit(100)
    rows = await cursor.to_list(length=100)
    for row in rows:
        if isinstance(row.get("created_at"), datetime):
            row["created_at"] = row["created_at"].isoformat()
    return {"messages": list(reversed(rows))}

@app.websocket("/ws/online")
async def online_ws(ws: WebSocket, token: str):
    await ws.accept()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = await db.users.find_one({"_id": payload["sub"]})
        if not user:
            await ws.close(code=4401); return
        uid = user["_id"]
        sockets[uid] = ws
        await ws.send_json({"type": "connected", "user_id": uid})
        while True:
            data = await ws.receive_json()
            if data.get("type") == "voice":
                packet = {"type": "voice", "from": uid, "nickname": user["nickname"], "audio": data.get("audio")}
                for other_id, other in list(sockets.items()):
                    if other_id != uid:
                        try: await other.send_json(packet)
                        except Exception: pass
            elif data.get("type") == "position":
                await db.positions.update_one({"user_id": uid}, {"$set": {
                    "user_id": uid, "nickname": user["nickname"], "lat": data.get("lat", 0),
                    "lon": data.get("lon", 0), "altitude": data.get("altitude", 1000),
                    "heading": data.get("heading", 0), "aircraft": data.get("aircraft", "a320"),
                    "updated_at": datetime.now(timezone.utc)}}, upsert=True)
                for other_id, other in list(sockets.items()):
                    if other_id != uid:
                        try: await other.send_json({"type": "position", "player": data | {"user_id": uid, "nickname": user["nickname"]}})
                        except Exception: pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if 'uid' in locals():
            sockets.pop(uid, None)
            await db.positions.delete_one({"user_id": uid})

@app.get("/", response_class=HTMLResponse)
async def home():
    with open("web/index.html", encoding="utf-8") as f:
        return f.read()

@app.get("/preview", response_class=HTMLResponse)
async def preview():
    with open("web/index.html", encoding="utf-8") as f:
        return f.read()

app.mount("/static", StaticFiles(directory="web"), name="static")
