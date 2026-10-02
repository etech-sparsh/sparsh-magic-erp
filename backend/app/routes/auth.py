from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import Optional
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timedelta
from app.db.mongodb import get_collection
from app.config.settings import settings

from app.models.user import UserCreate, UserResponse
from app.models.auth import Token, PasswordChange
from app.controllers.auth_controller import (
    get_password_hash, 
    verify_password, 
    create_access_token,
    get_current_active_user,
    get_current_user
)
from bson import ObjectId
import random
import logging

logger = logging.getLogger("auth")
from app.models.auth import Token, PasswordChange, ForgotPasswordRequest, ResetPasswordRequest, AdminMemberUpdate
from app.services.activity_log_service import log_activity
from app.services.notification_service import send_notification_from_template, send_otp_email

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest, background_tasks: BackgroundTasks):
    email = data.email.lower().strip()
    
    # 1. Search across both staff and learners
    user = await get_collection("staff").find_one({"email": email})
    if not user:
        user = await get_collection("learners").find_one({"email": email})
    
    if not user:
        # Security: Return generic message so we don't leak user emails
        return {"message": "If your email is registered, you will receive a 6-digit OTP."}

    # 2. Generate 6-digit OTP
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    
    # 3. Store OTP in password_resets collection
    resets_col = get_collection("password_resets")
    expires_at = datetime.utcnow() + timedelta(seconds=60)
    
    await resets_col.update_one(
        {"email": email},
        {"$set": {"otp": otp, "expires_at": expires_at}},
        upsert=True
    )
    
    # 4. Send background email
    background_tasks.add_task(send_otp_email, email, otp, user)
    
    await log_activity(user, "Password Reset OTP Requested", "auth", f"OTP generated for {email}")
    return {"message": "OTP has been sent to your registered email address."}

@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest):
    email = data.email.lower().strip()
    resets_col = get_collection("password_resets")
    
    # 1. Verify OTP record
    record = await resets_col.find_one({"email": email})
    if not record:
        raise HTTPException(status_code=400, detail="No reset request found for this email")
    
    if record["otp"] != data.otp:
        raise HTTPException(status_code=400, detail="Invalid verification code")
    
    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Verification code has expired")
    
    # 2. Identify collection and update password
    hashed_password = get_password_hash(data.new_password)
    col_name = None
    
    user = await get_collection("staff").find_one({"email": email})
    if user:
        col_name = "staff"
    else:
        user = await get_collection("learners").find_one({"email": email})
        if user:
            col_name = "learners"
            
    if not col_name:
        raise HTTPException(status_code=404, detail="Account not found during reset")
        
    await get_collection(col_name).update_one(
        {"email": email},
        {"$set": {"password": hashed_password}}
    )
    
    # 3. Cleanup reset record
    await resets_col.delete_one({"email": email})
    
    await log_activity(user, "Password Reset Completed", "auth", "Password successfully changed via OTP verification")
    return {"message": "Your password has been reset successfully. You can now login with your new password."}

@router.post("/request-admin-otp")
async def request_admin_otp(current_user: dict = Depends(get_current_active_user), background_tasks: BackgroundTasks = BackgroundTasks()):
    if current_user["role"] not in ["superadmin", "admin", "clientadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    resets_col = get_collection("password_resets")
    expires_at = datetime.utcnow() + timedelta(seconds=60)
    
    await resets_col.update_one(
        {"email": current_user["email"]},
        {"$set": {"otp": otp, "expires_at": expires_at}},
        upsert=True
    )
    
    background_tasks.add_task(send_otp_email, current_user["email"], otp, current_user)
    return {"message": "Verification code sent to your email."}

@router.post("/admin/update-member")
async def admin_update_member(data: AdminMemberUpdate, current_user: dict = Depends(get_current_active_user)):
    if current_user["role"] not in ["superadmin", "admin", "clientadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # 1. Verify OTP
    resets_col = get_collection("password_resets")
    record = await resets_col.find_one({"email": current_user["email"]})
    if not record or record["otp"] != data.otp or datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
        
    # 2. Find target user
    col_name = None
    target_user = await get_collection("staff").find_one({"_id": ObjectId(data.user_id)})
    if target_user:
        col_name = "staff"
    else:
        target_user = await get_collection("learners").find_one({"_id": ObjectId(data.user_id)})
        if target_user:
            col_name = "learners"
            
    if not col_name:
        raise HTTPException(status_code=404, detail="Target member not found")
        
    # 3. Authorization check
    if current_user["role"] == "clientadmin":
        if str(target_user.get("company_id")) != str(current_user.get("company_id")):
            raise HTTPException(status_code=403, detail="Not authorized to manage members of other companies")
            
    # 4. Perform updates
    update_dict = {}
    if data.new_email:
        update_dict["email"] = data.new_email.lower().strip()
    if data.new_password:
        update_dict["password"] = get_password_hash(data.new_password)
        
    if not update_dict:
        raise HTTPException(status_code=400, detail="No updates provided")
        
    await get_collection(col_name).update_one({"_id": ObjectId(data.user_id)}, {"$set": update_dict})
    
    # 5. Cleanup
    await resets_col.delete_one({"email": current_user["email"]})
    
    await log_activity(current_user, "Admin Action: Member Credentials Updated", "auth", f"Updated credentials for {target_user.get('email')} (ID: {data.user_id})")
    return {"message": "Member credentials updated successfully."}

@router.patch("/change-password")
async def change_password(data: PasswordChange, current_user: dict = Depends(get_current_active_user)):
    # Verify current password
    if not verify_password(data.current_password, current_user["password"]):
        raise HTTPException(status_code=400, detail="Incorrect current password")

    # Spec §15 — the new password must be at least 6 characters and must not repeat the
    # current one. Compared against the stored hash, so an identical password is caught
    # even though we never hold the old plaintext.
    if len(data.new_password or "") < 6:
        raise HTTPException(status_code=400,
                            detail="New password must be at least 6 characters long.")
    if verify_password(data.new_password, current_user["password"]):
        raise HTTPException(status_code=400,
                            detail="New password must be different from your current password.")

    # Hash and update
    hashed_password = get_password_hash(data.new_password)
    col_name = "staff" if current_user["role"] in ["superadmin", "admin", "coach", "staff"] else "learners"
    await get_collection(col_name).update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password": hashed_password}}
    )
    
    await log_activity(current_user, "Password Change", "auth", "Changed password via profile")
    return {"message": "Password updated successfully"}


@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate, background_tasks: BackgroundTasks, current_user: Optional[dict] = Depends(get_current_user)):
    role = user.role.lower()
    is_staff_role = role in ["superadmin", "admin", "coach", "staff"]
    
    # ─── Restrict Staff Creation to Superadmin ───
    if is_staff_role:
        if not current_user or current_user.get("role") != "superadmin":
            raise HTTPException(status_code=403, detail="Only superadmin can create staff users")
            
    collection_name = "staff" if is_staff_role else "learners"
    col = get_collection(collection_name)

    if await col.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    # Store raw password temporarily to send in email (if needed) or just confirm creation
    raw_password = user.password
    hashed_password = get_password_hash(user.password)
    user_dict = user.model_dump()
    user_dict["password"] = hashed_password
    user_dict["tag"] = "staff" if is_staff_role else "learner"
    fn = user.first_name or ""
    ln = user.last_name or ""
    user_dict["full_name"] = f"{fn} {ln}".strip()
    user_dict["created_at"] = datetime.utcnow()
    
    result = await col.insert_one(user_dict)
    user_dict["_id"] = str(result.inserted_id)
    
    # Send Welcome Email via Template
    background_tasks.add_task(
        send_notification_from_template,
        user_obj=user_dict,
        template_slug="user_creation", # The function appends _email or _whatsapp
        context={
            "name": user_dict["first_name"],
            "email": user_dict["email"],
            "password": raw_password,
            "role": user_dict["role"],
            "login_url": "https://sparsh.app/login"
        },

        delivery_type="email"
    )


    await log_activity(user_dict, "Registration Success", "auth", f"Registered as {role}")
    return user_dict


@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    logger.info(f"Login attempt for username: {form_data.username}")
    # Search Staff first
    user = await get_collection("staff").find_one({"email": form_data.username})
    if not user:
        # Search Learners
        user = await get_collection("learners").find_one({"email": form_data.username})

    if not user or not verify_password(form_data.password, user["password"]):
        logger.warning(f"Login failed (invalid credentials) for username: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.get("is_active") == False:
        logger.warning(f"Login blocked (deactivated account): {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact your administrator."
        )

    logger.info(f"Login success for {user.get('email')} (role={user.get('role')}, id={user.get('_id')})")
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user["email"], 
            "role": user["role"],
            "full_name": user.get("full_name") or f"{user.get('first_name') or ''} {user.get('last_name') or ''}".strip() or "User",
            "email": user.get("email"),
            "mobile": user.get("mobile"),
            "designation": user.get("designation"),
            "department": user.get("department"),
            "session_type": user.get("session_type"),
            "_id": str(user["_id"]),
            "company_id": user.get("company_id"),
            "permissions": user.get("permissions", {})
        }, 
        expires_delta=access_token_expires
    )
    await log_activity(user, "User Login", "auth", "Logged in via Token")
    return {"access_token": access_token, "token_type": "bearer"}
