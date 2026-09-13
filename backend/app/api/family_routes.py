"""Small version-checked demo-family editing endpoints."""

from fastapi import APIRouter, HTTPException, Request

from app.models.family import FamilyUpdate, PolicyUpdate, PreferencesUpdate
from app.repositories.family_repository import FamilyVersionConflict

router = APIRouter(prefix="/family", tags=["family"])


def _service(request: Request):
    return request.app.state.recovery_service.family_service


def _response(service, profile):
    return {**profile.model_dump(mode="json"), "locations": service.locations()}


def _update(request, method, body):
    service = _service(request)
    try:
        return _response(service, getattr(service, method)(body))
    except FamilyVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def get_family(request: Request):
    return _response(_service(request), _service(request).get())


@router.post("/reset")
def reset_demo_family(request: Request):
    return _response(_service(request), _service(request).reset_demo())


@router.put("")
def update_family(request: Request, body: FamilyUpdate):
    return _update(request, "update", body)


@router.get("/preferences")
def get_preferences(request: Request):
    profile = _service(request).get()
    return {"version": profile.version, "preferences": profile.preferences}


@router.put("/preferences")
def update_preferences(request: Request, body: PreferencesUpdate):
    return _update(request, "update_preferences", body)


@router.get("/policy")
def get_policy(request: Request):
    profile = _service(request).get()
    return {
        "version": profile.version,
        "policy": profile.policy,
        "notification_mode": profile.notification_mode,
    }


@router.put("/policy")
def update_policy(request: Request, body: PolicyUpdate):
    return _update(request, "update_policy", body)
