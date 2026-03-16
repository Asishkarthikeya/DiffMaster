"""Policy management API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.policy import Policy, PolicyRule
from app.schemas.policy import (
    PolicyCreate,
    PolicyListOut,
    PolicyOut,
    PolicyRuleCreate,
    PolicyRuleOut,
    PolicyUpdate,
)

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=PolicyListOut)
async def list_policies(
    scope: str | None = None,
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Policy)

    if scope:
        stmt = stmt.where(Policy.scope == scope)
    if is_active is not None:
        stmt = stmt.where(Policy.is_active == is_active)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Policy.priority.desc(), Policy.name)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    policies = list(result.scalars().all())

    return PolicyListOut(
        policies=[PolicyOut.model_validate(p) for p in policies],
        total=total,
    )


@router.post("", response_model=PolicyOut, status_code=201)
async def create_policy(
    data: PolicyCreate,
    session: AsyncSession = Depends(get_db),
):
    existing = (
        await session.execute(select(Policy).where(Policy.name == data.name))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Policy with this name already exists")

    policy = Policy(
        name=data.name,
        description=data.description,
        scope=data.scope,
        priority=data.priority,
    )
    session.add(policy)
    await session.flush()

    for rule_data in data.rules:
        rule = PolicyRule(
            policy_id=policy.id,
            name=rule_data.name,
            rule_type=rule_data.rule_type,
            pattern=rule_data.pattern,
            message=rule_data.message,
            severity=rule_data.severity,
            file_glob=rule_data.file_glob,
            config=rule_data.config,
        )
        session.add(rule)

    await session.flush()
    await session.refresh(policy)

    return PolicyOut.model_validate(policy)


@router.get("/{policy_id}", response_model=PolicyOut)
async def get_policy(
    policy_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Policy).where(Policy.id == policy_id)
    result = await session.execute(stmt)
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    return PolicyOut.model_validate(policy)


@router.patch("/{policy_id}", response_model=PolicyOut)
async def update_policy(
    policy_id: uuid.UUID,
    data: PolicyUpdate,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Policy).where(Policy.id == policy_id)
    result = await session.execute(stmt)
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(policy, key, value)

    await session.flush()
    return PolicyOut.model_validate(policy)


@router.delete("/{policy_id}", status_code=204)
async def delete_policy(
    policy_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Policy).where(Policy.id == policy_id)
    result = await session.execute(stmt)
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    await session.delete(policy)


@router.post("/{policy_id}/rules", response_model=PolicyRuleOut, status_code=201)
async def add_policy_rule(
    policy_id: uuid.UUID,
    data: PolicyRuleCreate,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Policy).where(Policy.id == policy_id)
    result = await session.execute(stmt)
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    rule = PolicyRule(
        policy_id=policy.id,
        name=data.name,
        rule_type=data.rule_type,
        pattern=data.pattern,
        message=data.message,
        severity=data.severity,
        file_glob=data.file_glob,
        config=data.config,
    )
    session.add(rule)
    await session.flush()

    return PolicyRuleOut.model_validate(rule)


@router.delete("/{policy_id}/rules/{rule_id}", status_code=204)
async def delete_policy_rule(
    policy_id: uuid.UUID,
    rule_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(PolicyRule).where(
        PolicyRule.id == rule_id,
        PolicyRule.policy_id == policy_id,
    )
    result = await session.execute(stmt)
    rule = result.scalar_one_or_none()

    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    await session.delete(rule)
