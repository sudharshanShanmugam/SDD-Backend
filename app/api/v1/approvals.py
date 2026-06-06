"""
Approval workflow API routes.
Approval queue, review, comment.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.services.approval_service import ApprovalService, _serialize_approval

logger = logging.getLogger(__name__)
router = APIRouter()


class ApprovalCommentRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    comment: str | None = None


class ApprovalResponse(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    entity_title: str
    project_id: str
    status: str
    requested_by: str
    reviewer_id: str | None
    due_date: str | None
    priority: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ApprovalHistoryEntry(BaseModel):
    id: str
    action: str
    actor_id: str
    actor_name: str
    comment: str | None
    created_at: str

    class Config:
        from_attributes = True


@router.get(
    "/queue",
    summary="Get pending approvals for current user",
)
async def get_approval_queue(
    project_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the pending approval items assigned to or visible to the current user.
    Sorted by priority and due date.
    """
    svc = ApprovalService(db)
    return await svc.get_queue(
        reviewer_id=str(current_user.id),
        project_id=project_id,
        entity_type=entity_type,
        priority=priority,
        page=page,
        page_size=page_size,
    )


@router.get(
    "",
    summary="List all approval items",
)
async def list_approvals(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    requested_by: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ApprovalService(db)
    return await svc.list_approvals(
        user_id=str(current_user.id),
        project_id=project_id,
        status=status,
        requested_by=requested_by,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{approval_id}",
    summary="Get approval item details",
)
async def get_approval(
    approval_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = ApprovalService(db)
    approval = await svc.get_by_id(approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    return _serialize_approval(approval)


@router.post(
    "/{approval_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve an item",
)
async def approve(
    approval_id: str,
    payload: ApprovalCommentRequest | None = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve the item. Optionally provide a comment."""
    svc = ApprovalService(db)
    approval = await svc.get_by_id(approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    approval_status = approval.status
    if hasattr(approval_status, "value"):
        approval_status = approval_status.value
    if str(approval_status) != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve an item with status '{approval_status}'.",
        )

    result = await svc.approve(
        approval_id=approval_id,
        reviewer_id=str(current_user.id),
        comment=payload.comment if payload else None,
    )
    return result


@router.post(
    "/{approval_id}/reject",
    status_code=status.HTTP_200_OK,
    summary="Reject an item",
)
async def reject(
    approval_id: str,
    payload: RejectRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject the item with a required reason."""
    svc = ApprovalService(db)
    approval = await svc.get_by_id(approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    approval_status = approval.status
    if hasattr(approval_status, "value"):
        approval_status = approval_status.value
    if str(approval_status) != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject an item with status '{approval_status}'.",
        )

    result = await svc.reject(
        approval_id=approval_id,
        reviewer_id=str(current_user.id),
        reason=payload.reason,
        comment=payload.comment,
    )
    return result


@router.post(
    "/{approval_id}/comment",
    status_code=status.HTTP_201_CREATED,
    summary="Add comment to approval",
)
async def add_comment(
    approval_id: str,
    payload: ApprovalCommentRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a review comment without changing approval status."""
    svc = ApprovalService(db)
    approval = await svc.get_by_id(approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")

    return await svc.add_comment(
        approval_id=approval_id,
        actor_id=str(current_user.id),
        comment=payload.comment,
    )


@router.get(
    "/{approval_id}/history",
    summary="Get approval history",
)
async def get_approval_history(
    approval_id: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full activity history for an approval item."""
    svc = ApprovalService(db)
    approval = await svc.get_by_id(approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")
    return await svc.get_history(approval_id=approval_id)


@router.post(
    "/{approval_id}/request-changes",
    status_code=status.HTTP_200_OK,
    summary="Request changes on an approval",
)
async def request_changes(
    approval_id: str,
    payload: RejectRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request changes without fully rejecting. Item goes to 'changes_requested' status."""
    svc = ApprovalService(db)
    approval = await svc.get_by_id(approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found.")

    return await svc.request_changes(
        approval_id=approval_id,
        reviewer_id=str(current_user.id),
        reason=payload.reason,
        comment=payload.comment,
    )
