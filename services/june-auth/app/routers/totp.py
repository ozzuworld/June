import io, base64
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from google.cloud import firestore
from app.deps_firebase import get_current_user, User
from app.deps_mfa import *

router = APIRouter(prefix="/auth/totp", tags=["mfa"])

@router.get("/status")
def status(user: User = Depends(get_current_user)):
    snap = totp_doc(user.uid).get()
    if not snap.exists:
        return {"enabled": False}
    return {"enabled": bool(snap.to_dict().get("enabled"))}

@router.post("/enroll/start")
def enroll_start(user: User = Depends(get_current_user)):
    ref = totp_doc(user.uid)
    snap = ref.get()
    if snap.exists and snap.to_dict().get("enabled"):
        raise HTTPException(400, "TOTP already enabled")

    secret = gen_secret()
    ref.set({
        "enabled": False,
        "secret_enc": enc(secret),
        "alg": ALG, "digits": DIGITS, "period": PERIOD,
        "created_at": firestore.SERVER_TIMESTAMP
    }, merge=True)

    provisioning_uri = build_totp(secret).provisioning_uri(name=user.email or user.uid, issuer_name=ISSUER)
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    b64png = base64.b64encode(buf.getvalue()).decode()

    return {"provisioning_uri": provisioning_uri, "qr_png_base64": f"data:image/png;base64,{b64png}"}

@router.post("/enroll/verify")
def enroll_verify(code: str, user: User = Depends(get_current_user)):
    ref = totp_doc(user.uid); snap = ref.get()
    if not snap.exists:
        raise HTTPException(400, "No enrollment found")
    data = snap.to_dict()
    if data.get("enabled"):
        return {"enabled": True}

    secret = dec(data["secret_enc"])
    if not build_totp(secret).verify(code, valid_window=1):
        raise HTTPException(400, "Invalid code")

    raw_codes = create_recovery_codes()
    ref.set({
        "enabled": True,
        "verified_at": firestore.SERVER_TIMESTAMP,
        "recovery_codes": hash_codes(raw_codes)
    }, merge=True)
    return {"enabled": True, "recovery_codes": raw_codes}

@router.post("/verify")
def verify(code: str | None = None, recovery_code: str | None = None, user: User = Depends(get_current_user)):
    snap = totp_doc(user.uid).get()
    if not snap.exists or not snap.to_dict().get("enabled"):
        # Optional: pass-through when user hasn't enrolled yet
        return {"mfa_token": mint_mfa_jwt(user.uid)}

    data = snap.to_dict()
    if recovery_code:
        if not verify_code_against_hashes(recovery_code, data.get("recovery_codes", [])):
            raise HTTPException(400, "Invalid recovery code")
        return {"mfa_token": mint_mfa_jwt(user.uid)}

    if not code:
        raise HTTPException(400, "Code required")
    secret = dec(data["secret_enc"])
    if not build_totp(secret).verify(code, valid_window=1):
        raise HTTPException(400, "Invalid code")

    return {"mfa_token": mint_mfa_jwt(user.uid)}

@router.post("/disable")
def disable(code: str, user: User = Depends(get_current_user)):
    ref = totp_doc(user.uid); snap = ref.get()
    if not snap.exists or not snap.to_dict().get("enabled"):
        return {"enabled": False}
    secret = dec(snap.to_dict()["secret_enc"])
    if not build_totp(secret).verify(code, valid_window=1):
        raise HTTPException(400, "Invalid code")
    ref.set({"enabled": False}, merge=True)
    return {"enabled": False}
