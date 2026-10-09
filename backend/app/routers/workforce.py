"""
LegacyWorkforce: the owner's AI workforce — up to 6 AI staff in each of the 5 departments (30 in all), picked from the
82 roles and swapped any time. Hired roles work in the AI office (the Chief of Staff can hand them jobs) and can be run
directly from here.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import roles_catalog
from ..context import Ctx, feature
from ..db import db, now
from ..services import track

router = APIRouter(prefix="/api/workforce")

RECOMMENDED = {"marketing": [7, 8, 9, 10, 11, 12], "sales": [19, 21, 23, 24, 28, 35], "support": [36, 43, 44, 45, 46, 49],
               "intelligence": [51, 52, 53, 56, 58, 60], "operations": [65, 67, 69, 71, 72, 77]}


class RoleIn(BaseModel):
    role_id: int = Field(ge=1, le=82)


async def _hired(ws: str) -> list[int]:
    doc = await db().workforce.find_one({"_id": ws}) or {}
    return [int(x) for x in doc.get("hired") or []]


async def _view(ws: str) -> dict:
    hired = set(await _hired(ws))
    week = {}
    async for e in db().outputs.aggregate([{"$match": {"user_id": ws, "kind": {"$regex": "^tool:role:"}}},
                                           {"$group": {"_id": "$kind", "n": {"$sum": 1}}}]):
        week[e["_id"][10:]] = e["n"]
    depts = []
    for d in roles_catalog.DEPARTMENTS:
        roles = [{**{k: v for k, v in r.items() if k != "produce"}, "hired": r["id"] in hired, "drafts": week.get(str(r["id"]), 0)}
                 for r in roles_catalog.ROLES if r["department"] == d["id"]]
        depts.append({**d, "roles": roles, "hired": sum(1 for r in roles if r["hired"])})
    return {"departments": depts, "per_department": roles_catalog.PER_DEPARTMENT, "hired": len(hired),
            "max": roles_catalog.PER_DEPARTMENT * len(roles_catalog.DEPARTMENTS), "total_roles": len(roles_catalog.ROLES)}


@router.get("")
async def workforce(ctx: Ctx = Depends(feature("workforce", "manager"))):
    return await _view(ctx.ws)


@router.post("/hire")
async def hire(body: RoleIn, ctx: Ctx = Depends(feature("workforce", "owner"))):
    r = roles_catalog.role(body.role_id)
    if not r:
        raise HTTPException(404, "No such role")
    hired = await _hired(ctx.ws)
    if r["id"] in hired:
        return await _view(ctx.ws)
    in_dept = sum(1 for x in hired if roles_catalog.department_of(x) == r["department"])
    if in_dept >= roles_catalog.PER_DEPARTMENT:
        name = next(d["name"] for d in roles_catalog.DEPARTMENTS if d["id"] == r["department"])
        raise HTTPException(400, f"{name} already has {roles_catalog.PER_DEPARTMENT} AI staff. Release one to add the {r['name']}.")
    await db().workforce.update_one({"_id": ctx.ws}, {"$addToSet": {"hired": r["id"]}, "$set": {"updated_at": now()}}, upsert=True)
    await track("role_hired", ctx.ws, role=r["id"])
    return await _view(ctx.ws)


@router.post("/release")
async def release(body: RoleIn, ctx: Ctx = Depends(feature("workforce", "owner"))):
    await db().workforce.update_one({"_id": ctx.ws}, {"$pull": {"hired": body.role_id}, "$set": {"updated_at": now()}})
    return await _view(ctx.ws)


@router.post("/recommended")
async def recommended(ctx: Ctx = Depends(feature("workforce", "owner"))):
    """Start with the recommended 30: the ten fully wired roles plus the most useful ones in each department."""
    ids = [i for ids in RECOMMENDED.values() for i in ids]
    await db().workforce.update_one({"_id": ctx.ws}, {"$set": {"hired": ids, "updated_at": now()}}, upsert=True)
    await track("workforce_recommended", ctx.ws)
    return await _view(ctx.ws)
