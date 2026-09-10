"""FastAPI entrypoint for the DayMend backend."""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import allowed_origins, build_application_service
from app.api.routes import router
from app.application import ApplicationError, RecoveryApplicationService
from app.repositories import (
    RecoveryCaseNotFound,
    RecoveryCaseVersionConflict,
)
from app.services import WorkflowInvariantError


def create_app(service: RecoveryApplicationService | None = None) -> FastAPI:
    application = FastAPI(
        title="DayMend API",
        description="Childcare disruption recovery lifecycle API.",
        version="0.1.0",
    )
    application.state.recovery_service = service or build_application_service()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Accept",
            "Last-Event-ID",
            "X-DayMend-Progress-ID",
        ],
    )

    @application.exception_handler(RecoveryCaseNotFound)
    async def recovery_not_found(_request: Request, _exc: RecoveryCaseNotFound) -> JSONResponse:
        return _error(
            status.HTTP_404_NOT_FOUND,
            "RECOVERY_CASE_NOT_FOUND",
            "Recovery case was not found.",
        )

    @application.exception_handler(RecoveryCaseVersionConflict)
    async def repository_conflict(
        _request: Request,
        _exc: RecoveryCaseVersionConflict,
    ) -> JSONResponse:
        return _error(
            status.HTTP_409_CONFLICT,
            "PERSISTENCE_CONFLICT",
            "Recovery case changed; reload it and retry.",
        )

    @application.exception_handler(ApplicationError)
    async def application_error(_request: Request, exc: ApplicationError) -> JSONResponse:
        return _error(status.HTTP_409_CONFLICT, exc.code, str(exc))

    @application.exception_handler(WorkflowInvariantError)
    async def workflow_error(_request: Request, exc: WorkflowInvariantError) -> JSONResponse:
        message = str(exc)
        if "does not belong" in message:
            return _error(
                status.HTTP_404_NOT_FOUND,
                "APPROVAL_NOT_FOUND",
                "Approval request was not found for this recovery case.",
            )
        if "cannot change finalized" in message:
            code = "APPROVAL_ALREADY_FINALIZED"
        elif "stale" in message or "current active plan" in message:
            code = "STALE_APPROVAL"
        else:
            code = "INVALID_RECOVERY_STATE"
        return _error(status.HTTP_409_CONFLICT, code, message)

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception) -> JSONResponse:
        return _error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "DayMend could not complete the request.",
        )

    application.include_router(router)
    return application


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


app = create_app()
