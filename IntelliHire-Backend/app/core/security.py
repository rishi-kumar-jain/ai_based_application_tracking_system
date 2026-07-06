from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

import requests
import jwt
from jwt.exceptions import InvalidTokenError
from jwt.algorithms import RSAAlgorithm  # <-- REQUIRED to convert Azure JWK to RSA key

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func as sa_func

from app.core.config import get_settings
from app.db.deps import get_db
from app.models.auth import User


bearer_scheme = HTTPBearer(auto_error=True)
   

@dataclass
class CurrentUser:
    user_id: int
    email: str
    full_name: str | None
    azure_oid: str | None
    roles: list[str]


@lru_cache(maxsize=1)
def get_azure_jwks() -> dict:
    """
    Fetch Azure AD public signing keys.
    Cached in memory after first call (thread-safe via lru_cache).
    To force a refresh: get_azure_jwks.cache_clear() then get_azure_jwks()
    """
    settings = get_settings()
    jwks_url = (
        f"https://login.microsoftonline.com/"
        f"{settings.azure_tenant_id}/discovery/v2.0/keys"
    )
    response = requests.get(jwks_url, timeout=10)
    response.raise_for_status()
    return response.json()


def _find_signing_key(token: str, force_refresh: bool = False) -> dict | None:
    """
    Finds the correct Azure signing key using JWT header kid.
    If force_refresh=True, clears the cache and fetches fresh keys from Azure.
    """
    unverified_header = jwt.get_unverified_header(token)
    token_kid = unverified_header.get("kid")

    if force_refresh:
        get_azure_jwks.cache_clear()

    jwks = get_azure_jwks()

    for key in jwks.get("keys", []):
        if key.get("kid") == token_kid:
            return key

    return None


def verify_azure_token(token: str) -> dict:
    """
    Validates Azure AD access token and returns decoded claims.
    """
    settings = get_settings()

    audience = settings.azure_audience
    issuer = f"https://sts.windows.net/{settings.azure_tenant_id}/"

    try:
        signing_key = _find_signing_key(token)

        # If key not found, refresh JWKS once because Azure keys may rotate
        if signing_key is None:
            signing_key = _find_signing_key(token, force_refresh=True)

        if signing_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signing key",
            )

        # ============================================================
        # FIX: Convert JWK (JSON dict from Azure) to an RSA key object
        # ============================================================
        public_key = RSAAlgorithm.from_jwk(signing_key)

        claims = jwt.decode(
            token,
            public_key,  # <--- Pass the RSA key object, NOT the raw dict
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
            },
        )

        token_tid = claims.get("tid")

        if token_tid != settings.azure_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token tenant",
            )

        return claims

    except HTTPException:
        raise

    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(e)}",
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """
    Extracts token from Authorization header,
    validates Azure AD token,
    extracts email,
    finds user in DB,
    loads assigned roles.
    """
    token = credentials.credentials

    claims = verify_azure_token(token)

    azure_oid = claims.get("oid")

    email = (
        claims.get("email")
        or claims.get("preferred_username")
        or claims.get("upn")
    )

    full_name = claims.get("name")

    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain email/preferred_username/upn claim",
        )

    email = email.lower().strip()

    user = (
        db.query(User)
        .options(joinedload(User.roles))
        .filter(sa_func.lower(User.email) == email)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not registered in IntelliHire",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    # Save Azure oid after first successful login
    if not user.azure_oid and azure_oid:
        user.azure_oid = azure_oid
        db.commit()
        db.refresh(user)

    # Safety check only if both values exist
    if user.azure_oid and azure_oid and user.azure_oid != azure_oid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token user does not match registered Azure user",
        )

    role_names = [role.role_name for role in user.roles]

    if not role_names:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no assigned role",
        )

    return CurrentUser(
        user_id=user.user_id,
        email=user.email,
        full_name=user.full_name or full_name,
        azure_oid=user.azure_oid,
        roles=role_names,
    )


def require_roles(allowed_roles: list[str]) -> Callable:
    """
    Role-based access guard.
    Allows request only if current user has at least one allowed role.
    """
    def dependency(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        user_roles = set(current_user.roles)
        allowed = set(allowed_roles)

        if not user_roles.intersection(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "Insufficient permissions",
                    "required_roles": allowed_roles,
                    "user_roles": current_user.roles,
                },
            )

        return current_user

    return dependency


require_admin = require_roles([
    "ADMIN",
])

require_recruiter = require_roles([
    "RECRUITER",
    "ADMIN",
])

require_hr_manager = require_roles([
    "HR",
    "ADMIN",
])

require_panelist = require_roles([
    "INTERVIEWER",
    "ADMIN",
])

require_any_role = require_roles([
    "RECRUITER",
    "INTERVIEWER",
    "HR",
    "ADMIN",
    "CEO",
])

require_ceo = require_roles([
    "CEO",
])