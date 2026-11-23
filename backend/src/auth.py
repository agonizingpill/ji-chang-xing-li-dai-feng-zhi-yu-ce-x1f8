import hashlib, os, jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .db import connect

bearer = HTTPBearer(auto_error=False)

def password_hash(value): return hashlib.sha256(value.encode()).hexdigest()
def issue(user): return jwt.encode({'sub': str(user['id']), 'username': user['username'], 'role': user['role'], 'exp': datetime.now(timezone.utc)+timedelta(hours=8)}, os.environ['JWT_SECRET'], algorithm='HS256')
def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials: raise HTTPException(401, '需要登录')
    try: payload = jwt.decode(credentials.credentials, os.environ['JWT_SECRET'], algorithms=['HS256'])
    except jwt.PyJWTError: raise HTTPException(401, '登录已过期')
    with connect() as conn:
        user = conn.execute('SELECT id,username,display_name,role FROM users WHERE id=%s AND active', (int(payload['sub']),)).fetchone()
    if not user: raise HTTPException(401, '账号不可用')
    return user

def require(*roles):
    def dep(user=Depends(current_user)):
        if user['role'] not in roles: raise HTTPException(403, '当前角色没有该操作权限')
        return user
    return dep
