"""Repository management API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.repository import Repository
from app.schemas.repository import (
    RepositoryCreate,
    RepositoryListOut,
    RepositoryOut,
    RepositoryUpdate,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get("", response_model=RepositoryListOut)
async def list_repositories(
    platform: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Repository)

    if platform:
        stmt = stmt.where(Repository.platform == platform)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Repository.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    repos = list(result.scalars().all())

    return RepositoryListOut(
        repositories=[RepositoryOut.model_validate(r) for r in repos],
        total=total,
    )


@router.post("", response_model=RepositoryOut, status_code=201)
async def create_repository(
    data: RepositoryCreate,
    session: AsyncSession = Depends(get_db),
):
    full_name = f"{data.owner}/{data.name}"

    existing_stmt = select(Repository).where(Repository.full_name == full_name)
    existing = (await session.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Repository already registered")

    repo = Repository(
        platform=data.platform,
        owner=data.owner,
        name=data.name,
        full_name=full_name,
        default_branch=data.default_branch,
        language=data.language,
        description=data.description,
        policy_pack_id=data.policy_pack_id,
    )
    session.add(repo)
    await session.flush()

    return RepositoryOut.model_validate(repo)


@router.get("/{repo_id}", response_model=RepositoryOut)
async def get_repository(
    repo_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Repository).where(Repository.id == repo_id)
    result = await session.execute(stmt)
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    return RepositoryOut.model_validate(repo)


@router.patch("/{repo_id}", response_model=RepositoryOut)
async def update_repository(
    repo_id: uuid.UUID,
    data: RepositoryUpdate,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Repository).where(Repository.id == repo_id)
    result = await session.execute(stmt)
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(repo, key, value)

    await session.flush()
    return RepositoryOut.model_validate(repo)


@router.delete("/{repo_id}", status_code=204)
async def delete_repository(
    repo_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Repository).where(Repository.id == repo_id)
    result = await session.execute(stmt)
    repo = result.scalar_one_or_none()

    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    await session.delete(repo)
