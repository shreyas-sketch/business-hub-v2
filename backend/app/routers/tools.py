"""API for ready-made AI tools and the LegacyWorkforce roles: /api/tools."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import plans, roles_catalog, tools
from ..context import Ctx, get_ctx
from ..db import db, public
from .hub import profile_of

router = APIRouter(prefix="/api/tools")


class RunIn(BaseModel):
    inputs: dict = Field(default_factory=dict)


async def hired_roles(ws: str) -> set[int]:
    doc = await db().workforce.find_one({"_id": ws}) or {}
    return {int(x) for x in doc.get("hired") or []}


async def context_for(owner: dict, ws: str, query: str) -> str:
    if not plans.has(owner, "company_brain"):
        return ""
    from ..company_brain import context
    return await context(ws, query)


@router.get("")
async def list_tools(ctx: Ctx = Depends(get_ctx)):
    """The tools library: every ready-made tool (locked ones show the plan that unlocks them). The 82 roles are listed
    on the Workforce page, so they are left out here unless the owner has the workforce."""
    hired = await hired_roles(ctx.ws) if ctx.has("workforce") else set()
    out = [t.view(ctx.owner, hired) for t in tools.TOOLS.values() if t.role_id is None and plans.META.get(t.feature, {}).get("on")]
    roles = [tools.TOOLS[f"role:{r}"].view(ctx.owner, hired) for r in sorted(hired)] if hired else []
    return {"desks": tools.DESKS, "tools": out, "roles": roles}


@router.post("/{key}/run")
async def run_tool(key: str, body: RunIn, ctx: Ctx = Depends(get_ctx)):
    t = tools.get(key)
    ctx.require(t.feature)
    if not ctx.at_least(t.role):
        raise HTTPException(403, "Ask your manager or the business owner to do this.")
    if t.role_id is not None and t.role_id not in await hired_roles(ctx.ws):
        raise HTTPException(400, f"Add the {t.name} to your workforce first (Workforce page).")
    profile = await profile_of(ctx.ws)
    query = " ".join(str(v) for v in body.inputs.values())[:500]
    return await tools.run(ctx.owner, ctx.ws, ctx.actor, key, body.inputs, profile, await context_for(ctx.owner, ctx.ws, query))


@router.get("/{key}/history")
async def history(key: str, ctx: Ctx = Depends(get_ctx)):
    t = tools.get(key)
    ctx.require(t.feature)
    return [public(o) async for o in db().outputs.find({"user_id": ctx.ws, "kind": f"tool:{key}"}).sort("created_at", -1).limit(30)]


@router.get("/roles/catalog")
async def catalog(ctx: Ctx = Depends(get_ctx)):
    """All 82 roles by department (shown on Workforce, and as a teaser below LegacyWorkforce)."""
    hired = await hired_roles(ctx.ws) if ctx.has("workforce") else set()
    return {"departments": roles_catalog.DEPARTMENTS, "per_department": roles_catalog.PER_DEPARTMENT,
            "roles": [{**{k: v for k, v in r.items() if k not in ("produce",)}, "hired": r["id"] in hired} for r in roles_catalog.ROLES]}
