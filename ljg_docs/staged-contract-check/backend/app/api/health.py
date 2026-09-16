from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.database import check_database_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    check_database_connection(request.app.state.database_engine)
    return HealthResponse(status="ok", database="ok")
