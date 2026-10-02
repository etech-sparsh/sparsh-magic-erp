from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from datetime import datetime, timedelta
from bson import ObjectId
import json
import math

from app.db.mongodb import get_collection
from app.controllers.auth_controller import get_current_user
from app.config.settings import settings
from app.services.s3_service import delete_file_from_s3
from openai import AsyncOpenAI

router = APIRouter(prefix="/media/ai", tags=["Media AI Chatbot"])

STAFF_ROLES = ["superadmin", "admin", "coach", "staff"]

def can_edit(user: dict) -> bool:
    return user.get("role") in STAFF_ROLES

def can_delete(user: dict) -> bool:
    return user.get("role") in STAFF_ROLES

# Helper to serialize mongo documents
def _serialize_media(doc: dict) -> dict:
    doc["id"] = str(doc["_id"])
    del doc["_id"]
    if "created_at" in doc and isinstance(doc["created_at"], datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc

@router.get("/folders")
async def list_folders(current_user: dict = Depends(get_current_user)):
    """List all custom folders created in the media library."""
    col = get_collection("media_folders")
    folders = await col.find({}).to_list(100)
    for f in folders:
        f["id"] = str(f["_id"])
        del f["_id"]
    return folders

@router.post("/folders")
async def create_folder(payload: dict, current_user: dict = Depends(get_current_user)):
    """Create a new folder in the media library."""
    if not can_edit(current_user):
        raise HTTPException(status_code=403, detail="Not authorized to create folders")
    
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    
    if not name.startswith("/"):
        name = "/" + name
        
    col = get_collection("media_folders")
    existing = await col.find_one({"name": name})
    if existing:
        return {"message": f"Folder {name} already exists", "folder": {"id": str(existing["_id"]), "name": name}}
        
    new_folder = {
        "name": name,
        "created_by": str(current_user["_id"]),
        "created_at": datetime.utcnow()
    }
    res = await col.insert_one(new_folder)
    return {"message": "Folder created successfully", "folder": {"id": str(res.inserted_id), "name": name}}

@router.get("/insights")
async def get_insights(current_user: dict = Depends(get_current_user)):
    """Retrieve media library insights."""
    return await tool_get_insights({}, current_user)

@router.get("/check-duplicate")
async def check_duplicate(filename: str, size: int, current_user: dict = Depends(get_current_user)):
    """Check if a file with the same name and size exists in the media library."""
    col = get_collection("media_library")
    existing = await col.find_one({"file_name": filename, "size": size})
    if existing:
        return {
            "duplicate": True,
            "type": "exact",
            "existing": _serialize_media(existing)
        }
        
    # Check by just same filename (potential duplicate)
    existing_name = await col.find_one({"file_name": filename})
    if existing_name:
        return {
            "duplicate": True,
            "type": "name_only",
            "existing": _serialize_media(existing_name)
        }
        
    return {"duplicate": False}

@router.post("/chat")
async def chat_interaction(payload: dict, current_user: dict = Depends(get_current_user)):
    """Interact with the Media Library AI assistant."""
    user_message = payload.get("message", "").strip()
    history = payload.get("history", [])
    current_folder = payload.get("current_folder", "/")
    
    if not user_message:
        raise HTTPException(status_code=400, detail="Message is required")
        
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    # 1. Define tools/functions for natural language task mapping
    tools = [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Search and filter files in the media library.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "media_type": {"type": "string", "enum": ["video", "audio", "pdf", "document", "image", "other", "all"]},
                        "name": {"type": "string", "description": "Search term matching filename or title"},
                        "folder": {"type": "string", "description": "Folder path like '/' or '/Marketing'"},
                        "tag": {"type": "string", "description": "Specific tag to search for"},
                        "min_size_mb": {"type": "number"},
                        "max_size_mb": {"type": "number"},
                        "uploaded_today": {"type": "boolean"},
                        "uploaded_this_week": {"type": "boolean"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_insights",
                "description": "Get dashboard metrics and insights (total files, storage, type distribution, upload trends).",
                "parameters": {"type": "object", "properties": {}}
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_folder",
                "description": "Create a new folder in the library.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Folder name (e.g. Marketing, Documents)"}
                    },
                    "required": ["name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "move_files",
                "description": "Move one or more files to a folder.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_ids": {"type": "array", "items": {"type": "string"}, "description": "IDs of files to move"},
                        "folder": {"type": "string", "description": "Target folder name (e.g. /Marketing)"}
                    },
                    "required": ["file_ids", "folder"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "rename_file",
                "description": "Rename an existing file in the media library.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "ID of the file to rename"},
                        "new_name": {"type": "string", "description": "New friendly name/title for the file"}
                    },
                    "required": ["file_id", "new_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_files",
                "description": "Delete one or more files from the library.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_ids": {"type": "array", "items": {"type": "string"}, "description": "IDs of files to delete"}
                    },
                    "required": ["file_ids"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_metadata",
                "description": "Update tags, categories or description for a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "description": {"type": "string"}
                    },
                    "required": ["file_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_metadata",
                "description": "Use AI to suggest tags, description, keywords, category, and alt-text for a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_id": {"type": "string", "description": "ID of the file to suggest metadata for"}
                    },
                    "required": ["file_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_duplicates",
                "description": "Identify potential duplicate files by name, size or content hash.",
                "parameters": {"type": "object", "properties": {}}
            }
        }
    ]
    
    # 2. Build system instructions
    current_time_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    system_prompt = f"""You are a helpful and intelligent AI Chatbot for the Media Library module.
Your role is to help users manage, search, organize, and inspect their files using natural language.
Current Time: {current_time_str} UTC
User Role: {current_user.get("role", "viewer")}
User Name: {current_user.get("name", "User")}
Current Folder View: {current_folder}

Adhere to the following safety rules:
1. Permissions:
   - Admin / SuperAdmin roles have FULL access.
   - Coach / Staff roles can upload, edit, move, tag, rename, and delete (Editors).
   - Learner / Viewer roles can ONLY search, view, read, and list files. They CANNOT create folders, delete files, move files, rename files, upload files, or update metadata. If a Viewer tries to perform a write/modify/delete action, politely decline citing their role.
2. Direct Conversational Responses:
   - For simple questions, chat naturally.
   - For file tasks, use the appropriate tool function. After executing the tool, explain what you did clearly.
   - CRITICAL: If asked to delete, rename, move, or tag a file by name, you MUST first use the `list_files` tool to search for the file and get its exact `id`. Do NOT guess file IDs.
"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})
    
    # 3. Call OpenAI for tool routing loop (max 5 iterations)
    MAX_ITERATIONS = 5
    iteration = 0
    
    frontend_action = None
    action_data = None
    
    while iteration < MAX_ITERATIONS:
        iteration += 1
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.4
        )
        
        response_message = response.choices[0].message
        tool_calls = response_message.tool_calls
        
        if not tool_calls:
            # AI has completed its tasks and provided a final message
            return {
                "role": "assistant",
                "content": response_message.content,
                "action": frontend_action,
                "action_data": action_data
            }
            
        messages.append(response_message)
        
        available_tools = {
            "list_files": tool_list_files,
            "get_insights": tool_get_insights,
            "create_folder": tool_create_folder,
            "move_files": tool_move_files,
            "rename_file": tool_rename_file,
            "delete_files": tool_delete_files,
            "update_metadata": tool_update_metadata,
            "suggest_metadata": tool_suggest_metadata,
            "get_duplicates": tool_get_duplicates
        }
        
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            
            # Handle potential JSON decode errors safely
            try:
                function_args = json.loads(tool_call.function.arguments)
            except Exception:
                function_args = {}
                
            tool_fn = available_tools.get(function_name)
            if tool_fn:
                # Call tool and inject current user context
                tool_result = await tool_fn(function_args, current_user)
                
                # Capture specific UI/UX updates to relay to the React app
                if function_name == "list_files":
                    frontend_action = "FILTER"
                    action_data = tool_result.get("filters", {})
                elif function_name == "create_folder" and "folder" in tool_result:
                    frontend_action = "CREATE_FOLDER"
                    action_data = tool_result["folder"]
                elif function_name in ["move_files", "rename_file", "delete_files", "update_metadata"] and tool_result.get("success"):
                    frontend_action = "REFRESH_FILES"
                elif function_name == "get_duplicates":
                    frontend_action = "DUPLICATES"
                    action_data = tool_result.get("duplicates", [])
                
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(tool_result),
                })
            else:
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps({"error": f"Unknown tool {function_name}"}),
                })

    # Fallback if iterations exceed limit
    return {
        "role": "assistant",
        "content": "I executed multiple steps. The task is complete.",
        "action": frontend_action,
        "action_data": action_data
    }

# ─── TOOL IMPLEMENTATIONS ───

async def tool_list_files(args: dict, user: dict) -> dict:
    media_type = args.get("media_type", "all")
    name = args.get("name", "")
    folder = args.get("folder", "")
    tag = args.get("tag", "")
    min_size = args.get("min_size_mb", 0) * 1024 * 1024
    max_size = args.get("max_size_mb", 0) * 1024 * 1024
    uploaded_today = args.get("uploaded_today", False)
    uploaded_this_week = args.get("uploaded_this_week", False)
    
    col = get_collection("media_library")
    query = {}
    
    if media_type and media_type != "all":
        query["media_type"] = media_type
        
    if name:
        query["$or"] = [
            {"name": {"$regex": name, "$options": "i"}},
            {"file_name": {"$regex": name, "$options": "i"}},
            {"description": {"$regex": name, "$options": "i"}}
        ]
        
    if folder:
        query["folder"] = folder
        
    if tag:
        query["tags"] = tag
        
    if min_size or max_size:
        size_query = {}
        if min_size: size_query["$gte"] = min_size
        if max_size: size_query["$lte"] = max_size
        query["size"] = size_query
        
    now = datetime.utcnow()
    if uploaded_today:
        today_start = datetime(now.year, now.month, now.day)
        query["created_at"] = {"$gte": today_start}
    elif uploaded_this_week:
        week_start = now - timedelta(days=7)
        query["created_at"] = {"$gte": week_start}
        
    items = await col.find(query).sort("created_at", -1).limit(50).to_list(50)
    serialized = [_serialize_media(i) for i in items]
    
    # Simplify response payload for LLM consumption
    return {
        "status": "success",
        "count": len(serialized),
        "files": [{"id": f["id"], "name": f["name"], "media_type": f["media_type"], "size": f.get("size", 0), "created_at": f.get("created_at")} for f in serialized],
        "filters": {
            "media_type": media_type,
            "search": name,
            "folder": folder,
            "tag": tag
        }
    }

async def tool_get_insights(args: dict, user: dict) -> dict:
    col = get_collection("media_library")
    all_files = await col.find({}).to_list(1000)
    
    total_files = len(all_files)
    total_size = sum(f.get("size", 0) for f in all_files)
    
    # Storage Usage formatted
    units = ['B', 'KB', 'MB', 'GB']
    i = 0
    size_n = total_size
    while size_n >= 1024 and i < len(units)-1:
        size_n /= 1024
        i += 1
    storage_formatted = f"{size_n:.2f} {units[i]}"
    
    # Type distribution
    type_counts = {}
    for f in all_files:
        t = f.get("media_type", "other")
        type_counts[t] = type_counts.get(t, 0) + 1
        
    # Top users
    user_counts = {}
    for f in all_files:
        uid = f.get("uploaded_by", "unknown")
        user_counts[uid] = user_counts.get(uid, 0) + 1
        
    # Resolve top user names if database is accessible
    resolved_users = {}
    user_ids = [ObjectId(uid) for uid in user_counts.keys() if ObjectId.is_valid(uid)]
    if user_ids:
        users = await get_collection("users").find({"_id": {"$in": user_ids}}).to_list(50)
        resolved_users = {str(u["_id"]): u.get("name", "User") for u in users}
        
    top_users = [
        {"name": resolved_users.get(uid, f"User {uid[:5]}..."), "uploads": count}
        for uid, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    # Recent activity
    recent_files = sorted(all_files, key=lambda x: x.get("created_at", datetime.min), reverse=True)[:5]
    recent_activity = [
        {"name": f.get("name"), "type": f.get("media_type"), "date": f.get("created_at").isoformat() if isinstance(f.get("created_at"), datetime) else ""}
        for f in recent_files
    ]
    
    return {
        "insights": {
            "total_files": total_files,
            "storage_usage": storage_formatted,
            "type_distribution": type_counts,
            "top_users": top_users,
            "recent_activity": recent_activity
        }
    }

async def tool_create_folder(args: dict, user: dict) -> dict:
    if not can_edit(user):
        return {"status": "error", "message": "Decline request: User lacks editor permissions to create folders."}
        
    name = args.get("name", "").strip()
    if not name:
        return {"status": "error", "message": "Folder name is empty"}
        
    if not name.startswith("/"):
        name = "/" + name
        
    col = get_collection("media_folders")
    existing = await col.find_one({"name": name})
    if existing:
        return {"status": "success", "message": f"Folder {name} already exists", "folder": {"id": str(existing["_id"]), "name": name}}
        
    new_folder = {
        "name": name,
        "created_by": str(user["_id"]),
        "created_at": datetime.utcnow()
    }
    res = await col.insert_one(new_folder)
    return {
        "status": "success", 
        "message": f"Folder '{name}' created successfully", 
        "folder": {"id": str(res.inserted_id), "name": name}
    }

async def tool_move_files(args: dict, user: dict) -> dict:
    if not can_edit(user):
        return {"status": "error", "message": "Decline request: User lacks editor permissions to move files."}
        
    file_ids = args.get("file_ids", [])
    folder = args.get("folder", "").strip()
    
    if not file_ids:
        return {"status": "error", "message": "No file IDs provided"}
    if not folder:
        return {"status": "error", "message": "Target folder is empty"}
        
    if not folder.startswith("/"):
        folder = "/" + folder
        
    # Auto create folder if it doesn't exist
    f_col = get_collection("media_folders")
    existing_folder = await f_col.find_one({"name": folder})
    if not existing_folder and folder != "/":
        await f_col.insert_one({
            "name": folder,
            "created_by": str(user["_id"]),
            "created_at": datetime.utcnow()
        })
        
    col = get_collection("media_library")
    oids = [ObjectId(fid) for fid in file_ids if ObjectId.is_valid(fid)]
    res = await col.update_many({"_id": {"$in": oids}}, {"$set": {"folder": folder}})
    
    return {
        "status": "success",
        "success": True,
        "message": f"Successfully moved {res.modified_count} file(s) to '{folder}'"
    }

async def tool_rename_file(args: dict, user: dict) -> dict:
    if not can_edit(user):
        return {"status": "error", "message": "Decline request: User lacks editor permissions to rename files."}
        
    file_id = args.get("file_id")
    new_name = args.get("new_name", "").strip()
    
    if not file_id or not ObjectId.is_valid(file_id):
        return {"status": "error", "message": "Invalid file ID"}
    if not new_name:
        return {"status": "error", "message": "New name cannot be empty"}
        
    col = get_collection("media_library")
    res = await col.update_one({"_id": ObjectId(file_id)}, {"$set": {"name": new_name}})
    
    if res.modified_count == 0:
        return {"status": "error", "message": "File not found or name was already identical"}
        
    return {"status": "success", "success": True, "message": f"File renamed to '{new_name}'"}

async def tool_delete_files(args: dict, user: dict) -> dict:
    if not can_delete(user):
        return {"status": "error", "message": "Decline request: User lacks permissions to delete files."}
        
    file_ids = args.get("file_ids", [])
    if not file_ids:
        return {"status": "error", "message": "No file IDs provided"}
        
    col = get_collection("media_library")
    oids = [ObjectId(fid) for fid in file_ids if ObjectId.is_valid(fid)]
    
    # Retrieve S3 keys first
    files = await col.find({"_id": {"$in": oids}}).to_list(100)
    for f in files:
        if f.get("s3_key"):
            delete_file_from_s3(f["s3_key"])
            
    res = await col.delete_many({"_id": {"$in": oids}})
    return {
        "status": "success",
        "success": True,
        "message": f"Successfully deleted {res.deleted_count} file(s) from database and S3 storage"
    }

async def tool_update_metadata(args: dict, user: dict) -> dict:
    if not can_edit(user):
        return {"status": "error", "message": "Decline request: User lacks editor permissions to update metadata."}
        
    file_id = args.get("file_id")
    tags = args.get("tags")
    description = args.get("description")
    
    if not file_id or not ObjectId.is_valid(file_id):
        return {"status": "error", "message": "Invalid file ID"}
        
    update_fields = {}
    if tags is not None:
        # Strip and deduplicate tags
        update_fields["tags"] = list(set([t.strip().lower() for t in tags if t.strip()]))
    if description is not None:
        update_fields["description"] = description.strip()
        
    if not update_fields:
        return {"status": "error", "message": "No update fields provided"}
        
    col = get_collection("media_library")
    await col.update_one({"_id": ObjectId(file_id)}, {"$set": update_fields})
    return {"status": "success", "success": True, "message": "Metadata updated successfully"}

async def tool_suggest_metadata(args: dict, user: dict) -> dict:
    file_id = args.get("file_id")
    if not file_id or not ObjectId.is_valid(file_id):
        return {"status": "error", "message": "Invalid file ID"}
        
    col = get_collection("media_library")
    doc = await col.find_one({"_id": ObjectId(file_id)})
    if not doc:
        return {"status": "error", "message": "File not found"}
        
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    prompt = f"""Generate smart metadata suggestions for this media file:
Filename: {doc.get("file_name")}
Display Name: {doc.get("name")}
Description: {doc.get("description", "No description")}
Type: {doc.get("media_type")}

Return a JSON object containing:
- tags: A list of 4-6 relevant descriptive keywords (lowercase strings)
- category: A single string categorizing the file (e.g. documentation, media, legal, finance, product)
- suggested_description: An enhanced/friendly descriptive summary
- alt_text: Alt text for accessibility (especially if an image, otherwise short helper context)

OUTPUT JSON FORMAT ONLY:
{{
  "tags": ["tag1", "tag2", ...],
  "category": "category_name",
  "suggested_description": "summary text",
  "alt_text": "alt text"
}}
"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        suggestions = json.loads(response.choices[0].message.content)
        
        # Save these suggestions directly to metadata (smart suggestion auto-save)
        await col.update_one(
            {"_id": ObjectId(file_id)}, 
            {"$set": {
                "tags": suggestions.get("tags", []),
                "category": suggestions.get("category", ""),
                "description": suggestions.get("suggested_description", doc.get("description")),
                "alt_text": suggestions.get("alt_text", "")
            }}
        )
        
        return {
            "status": "success",
            "message": "Metadata suggestions successfully applied to the file",
            "suggestions": suggestions
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to generate metadata suggestions: {str(e)}"}

async def tool_get_duplicates(args: dict, user: dict) -> dict:
    col = get_collection("media_library")
    all_files = await col.find({}).to_list(1000)
    
    # Simple grouping check: same filename or same filename + size
    duplicates_map = {}
    for f in all_files:
        key = f.get("file_name", "").lower()
        if not key: continue
        
        if key not in duplicates_map:
            duplicates_map[key] = []
        duplicates_map[key].append(_serialize_media(f))
        
    duplicates_list = []
    for filename, group in duplicates_map.items():
        if len(group) > 1:
            duplicates_list.append({
                "filename": filename,
                "count": len(group),
                "items": group
            })
            
    return {
        "status": "success",
        "duplicates": duplicates_list
    }
