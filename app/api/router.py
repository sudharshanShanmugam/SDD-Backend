"""
Main API router aggregating all v1 routes.
"""
from fastapi import APIRouter

from app.api.v1 import (
    auth,
    users,
    organizations,
    workspaces,
    projects,
    documents,
    requirements,
    epics,
    stories,
    sprints,
    tasks,
    approvals,
    qa,
    releases,
    ai,
    audit,
    notifications,
    search,
    analytics,
    admin,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["Organizations"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])
api_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(requirements.router, prefix="/requirements", tags=["Requirements"])
api_router.include_router(epics.router, prefix="/epics", tags=["Epics"])
api_router.include_router(stories.router, prefix="/stories", tags=["Stories"])
api_router.include_router(sprints.router, prefix="/sprints", tags=["Sprints"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["Approvals"])
api_router.include_router(qa.router, prefix="/qa", tags=["QA"])
api_router.include_router(releases.router, prefix="/releases", tags=["Releases"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(audit.router, prefix="/audit", tags=["Audit"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
