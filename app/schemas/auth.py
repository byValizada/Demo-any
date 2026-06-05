from pydantic import BaseModel, EmailStr
from typing import Optional


VALID_TENANT_TYPES = {"school", "repetitor", "academy", "corporate"}

class TenantCreate(BaseModel):
    name: str
    slug: str
    type: str = "repetitor"  # school | repetitor | academy | corporate


class InstitutionRegisterRequest(BaseModel):
    institution_name: str
    institution_type: str = "school"   # school | academy | corporate
    admin_name: str
    email: EmailStr
    password: str


class CorporateRegisterRequest(BaseModel):
    company_name: str      # şirkət adı
    industry: str = ""     # sahə (IT, Tibb, Maliyyə, ...)
    admin_name: str
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "teacher"  # teacher | student | parent | admin
    tenant: TenantCreate


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    id: str
    name: str
    email: str
    role: str
    tenant_id: str
    tenant_name: str
    tenant_plan: str = "free"   # free | repetitor | musessise | basic | pro
    tenant_type: str = "repetitor"  # repetitor | school | academy | corporate
    is_active: bool = True
    student_limit: int = 0

    class Config:
        from_attributes = True


class RefreshRequest(BaseModel):
    refresh_token: str
