import os
import uuid
import json
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, UploadFile, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()

# Configuration
STORAGE_PATHS = ["/storage", "/storage2", "/storage3"]
MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
DEFAULT_EXPIRY = 24 * 60 * 60  # 24h in seconds
DB_FILE = "file_db.json"
CHUNK_SIZE = 8192  # 8KB chunks for reading uploads

class FileDatabase:
    def __init__(self, db_file):
        self.db_file = db_file
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        if not os.path.exists(self.db_file):
            with open(self.db_file, 'w') as f:
                json.dump({"files": {}, "stats": {}}, f)
    
    def _read_db(self):
        with open(self.db_file, 'r') as f:
            return json.load(f)
    
    def _write_db(self, data):
        with open(self.db_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def add_file(self, file_id, file_data):
        db = self._read_db()
        db["files"][file_id] = file_data
        
        # Update stats
        storage_path = file_data["storage_path"]
        db["stats"][storage_path] = db["stats"].get(storage_path, 0) + 1
        
        self._write_db(db)
    
    def get_file(self, file_id):
        db = self._read_db()
        return db["files"].get(file_id)
    
    def delete_file(self, file_id):
        db = self._read_db()
        if file_id in db["files"]:
            file_data = db["files"][file_id]
            storage_path = file_data["storage_path"]
            
            # Update stats
            if storage_path in db["stats"]:
                db["stats"][storage_path] -= 1
                if db["stats"][storage_path] <= 0:
                    del db["stats"][storage_path]
            
            del db["files"][file_id]
            self._write_db(db)
            return True
        return False
    
    def get_expired_files(self):
        db = self._read_db()
        now = datetime.utcnow().isoformat()
        return [file_id for file_id, data in db["files"].items() if data["expires_at"] < now]
    
    def get_storage_stats(self):
        db = self._read_db()
        return db["stats"]

# Initialize database
db = FileDatabase(DB_FILE)

def setup_storage():
    """Ensure storage directories exist"""
    for path in STORAGE_PATHS:
        Path(path).mkdir(parents=True, exist_ok=True)

def select_storage_path():
    """Select storage path with least files (simple load balancing)"""
    stats = db.get_storage_stats()
    counts = {path: stats.get(path, 0) for path in STORAGE_PATHS}
    return min(counts.items(), key=lambda x: x[1])[0]

def cleanup_expired_files():
    """Remove expired files from storage and database"""
    expired_files = db.get_expired_files()
    for file_id in expired_files:
        file_data = db.get_file(file_id)
        if file_data:
            file_path = os.path.join(file_data["storage_path"], file_id)
            try:
                os.remove(file_path)
            except OSError:
                pass
            db.delete_file(file_id)

@app.on_event("startup")
async def startup_event():
    setup_storage()
    cleanup_expired_files()

@app.post("/api/files", status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile, expires_in: int = DEFAULT_EXPIRY):
    # Validate file size
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Max size is {MAX_FILE_SIZE} bytes"
        )
    
    # Select storage location
    storage_path = select_storage_path()
    file_id = str(uuid.uuid4())
    file_path = os.path.join(storage_path, file_id)
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
    
    # Save file
    file_size = 0
    try:
        with open(file_path, "wb") as f:
            while chunk := await file.read(CHUNK_SIZE):
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    os.remove(file_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File too large (max 5GB)"
                    )
                f.write(chunk)
    except IOError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage error: {str(e)}"
        )
    
    # Save metadata
    file_data = {
        "id": file_id,
        "original_name": file.filename,
        "size": file_size,
        "content_type": file.content_type,
        "storage_path": storage_path,
        "expires_at": expires_at,
        "uploaded_at": datetime.utcnow().isoformat()
    }
    db.add_file(file_id, file_data)
    
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "id": file_id,
            "url": f"/api/files/{file_id}",
            "download_url": f"/api/files/{file_id}/download",
            "info_url": f"/api/files/{file_id}/info",
            "expires_at": expires_at,
            "size": file_size,
            "max_size": MAX_FILE_SIZE,
            "storage_location": storage_path
        }
    )

@app.get("/api/files/{file_id}/download")
async def download_file(file_id: str):
    file_data = db.get_file(file_id)
    if not file_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    # Check if expired
    if datetime.fromisoformat(file_data["expires_at"]) < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="File has expired"
        )
    
    file_path = os.path.join(file_data["storage_path"], file_id)
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found in storage"
        )
    
    return FileResponse(
        file_path,
        filename=file_data["original_name"],
        media_type=file_data["content_type"]
    )

@app.get("/api/files/{file_id}/info")
async def get_file_info(file_id: str):
    file_data = db.get_file(file_id)
    if not file_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    expires_at = datetime.fromisoformat(file_data["expires_at"])
    remaining = expires_at - datetime.utcnow()
    
    return {
        "id": file_id,
        "original_name": file_data["original_name"],
        "size": file_data["size"],
        "content_type": file_data["content_type"],
        "storage_location": file_data["storage_path"],
        "uploaded_at": file_data["uploaded_at"],
        "expires_at": file_data["expires_at"],
        "remaining_seconds": max(0, remaining.total_seconds()),
        "expired": remaining.total_seconds() <= 0
    }

@app.delete("/api/files/{file_id}")
async def delete_file(file_id: str):
    file_data = db.get_file(file_id)
    if not file_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found"
        )
    
    file_path = os.path.join(file_data["storage_path"], file_id)
    try:
        os.remove(file_path)
    except OSError:
        pass
    
    db.delete_file(file_id)
    return {"status": "deleted", "id": file_id}

@app.get("/api/stats")
async def get_stats():
    stats = db.get_storage_stats()
    total_files = sum(stats.values())
    
    # Get storage usage for each path
    storage_info = []
    for path in STORAGE_PATHS:
        try:
            usage = os.statvfs(path)
            total = usage.f_frsize * usage.f_blocks
            free = usage.f_frsize * usage.f_bfree
            used = total - free
            storage_info.append({
                "path": path,
                "files": stats.get(path, 0),
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "used_percent": (used / total) * 100 if total > 0 else 0
            })
        except OSError:
            storage_info.append({
                "path": path,
                "error": "Storage path not accessible"
            })
    
    return {
        "total_files": total_files,
        "storage": storage_info,
        "max_file_size": MAX_FILE_SIZE,
        "default_expiry": DEFAULT_EXPIRY
    }
