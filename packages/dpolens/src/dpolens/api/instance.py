"""What a signed-in person needs to know about the instance itself.

The MCP server's address is a setting rather than something the dashboard works
out, because behind a proxy or on another port nothing on the page can know it.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from dpolens import __version__
from dpolens.api import problems
from dpolens.api.dependencies import Caller, Configured

router = APIRouter(prefix="/v1", tags=["instance"], responses=problems.responses(401, 403, 429))


class Instance(BaseModel):
    version: str
    mcp_url: str = Field(description="The MCP server's address, for an assistant's configuration")


@router.get("/instance", summary="The version, and where assistants connect")
def describe(who: Caller, settings: Configured) -> Instance:
    assert who  # any signed-in caller
    return Instance(version=__version__, mcp_url=settings.public_mcp_url)
