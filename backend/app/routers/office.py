"""The agentic office API (LegacyWorkforce plan): staff, instructions and their runs, and the morning standup."""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..agents import office
from ..agents.jobs import save_settings
from ..config import settings
from ..context import Ctx, feature
from ..db import db, now, public
from .hub import profile_of

router = APIRouter(prefix="/api/office")


class InstructionIn(BaseModel):
    instruction: str = Field(min_length=5, max_length=1500)


class StaffPatch(BaseModel):
    on: bool | None = None
    autonomy: Literal["ask", "act"] | None = None


@router.get("")
async def overview(ctx: Ctx = Depends(feature("agentic_office", "manager"))):
    from .. import roles_catalog
    s = await office.staff_settings(ctx.ws)
    hired = [roles_catalog.role(r) for r in await office.hired_roles(ctx.ws)]
    week_ago = now() - timedelta(days=7)
    staff = []
    for key, info in office.STAFF.items():
        actions = await db().agent_log.count_documents({"ws": ctx.ws, "agent": office.agent_key(key), "status": "done", "at": {"$gte": week_ago}})
        staff.append({"key": key, **info, "on": s[key].get("on", True), "autonomy": s[key].get("autonomy", "ask"),
                      "customer_facing": key in office.CUSTOMER_FACING, "actions_this_week": actions,
                      "roles": [{"id": r["id"], "name": r["name"]} for r in hired if r and r["department"] == key],
                      "tools": [{"name": n, "label": t["label"], "description": t["description"], "uses_ai": t["uses_ai"]}
                                for n, t in office.TOOLS.items() if t["staff"] == key and n != "role.draft"]})
    runs = [office.run_view(r) async for r in db().office_runs.find({"ws": ctx.ws}).sort("created_at", -1).limit(15)]
    standup = await db().outputs.find_one({"user_id": ctx.ws, "kind": "standup"}, sort=[("created_at", -1)])
    return {"staff": staff, "runs": runs, "standup": public(standup) if standup else None,
            "can_act": ctx.has("agents_act"), "hired": len([r for r in hired if r])}


@router.patch("/staff/{key}")
async def update_staff(key: str, body: StaffPatch, ctx: Ctx = Depends(feature("agentic_office", "owner"))):
    if key not in office.STAFF:
        raise HTTPException(404, "Not found")
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if patch.get("autonomy") == "act" and (not ctx.has("agents_act") or key not in office.CUSTOMER_FACING):
        raise HTTPException(400, "Only Sales and Customer support can act on their own. Money messages always wait for you.")
    await save_settings(ctx.ws, office.agent_key(key), patch)
    return {"ok": True}


@router.post("/runs")
async def give_instruction(body: InstructionIn, ctx: Ctx = Depends(feature("agentic_office", "manager"))):
    run = await office.start(ctx.owner, ctx.actor, body.instruction, await profile_of(ctx.ws), ctx.role)
    if settings.env == "test":
        run = await office.execute(run["_id"])  # deterministic in tests
    else:
        await office.spawn(run["_id"])
    return office.run_view(await db().office_runs.find_one({"_id": run["_id"]}))


@router.get("/runs/{run_id}")
async def get_run(run_id: str, ctx: Ctx = Depends(feature("agentic_office", "manager"))):
    run = await db().office_runs.find_one({"_id": run_id, "ws": ctx.ws})
    if not run:
        raise HTTPException(404, "Not found")
    return office.run_view(run)


@router.post("/standup")
async def standup_now(ctx: Ctx = Depends(feature("agentic_office", "owner"))):
    result = await office.write_standup(ctx.owner, now(), ctx.actor)
    return result


async def ensure_indexes() -> None:
    await db().office_runs.create_index([("ws", 1), ("created_at", -1)])
