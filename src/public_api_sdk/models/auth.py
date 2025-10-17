"""Authentication-related data models"""

from typing import Optional
from pydantic import BaseModel, Field


class AccessTokenResponse(BaseModel):
    access_token: str = Field(
        ..., alias="accessToken", description="Generated access token"
    )


class OAuthTokenResponse(BaseModel):
    access_token: str = Field(..., alias="access_token")
    token_type: str = Field(default="Bearer", alias="token_type")
    expires_in: Optional[int] = Field(None, alias="expires_in")
    refresh_token: Optional[str] = Field(None, alias="refresh_token")
    scope: Optional[str] = Field(None, alias="scope")
