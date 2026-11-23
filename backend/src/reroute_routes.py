"""行李带停用改送试算的 HTTP 路由：值班页面试算、重算、确认与容量调整。"""

from fastapi import APIRouter, Depends

from . import reroute_service as service
from .auth import current_user, require
from .schemas import BeltCapacityIn, RerouteConfirmIn, RerouteTrialIn

router = APIRouter(prefix='/reroute', tags=['行李带改送试算'])


@router.get('/overview')
def overview(user=Depends(current_user)):
    return service.overview()


@router.get('/plans')
def plans(user=Depends(current_user)):
    return service.list_plans()


@router.get('/plans/{plan_id}')
def plan_detail(plan_id: int, user=Depends(current_user)):
    return service.get_plan(plan_id)


@router.post('/trials', status_code=201)
def create_trial(data: RerouteTrialIn, user=Depends(require('operator', 'supervisor'))):
    return service.create_trial(data, user)


@router.post('/plans/{plan_id}/recalc', status_code=200)
def recalc(plan_id: int, user=Depends(require('operator', 'supervisor'))):
    return service.recalc(plan_id, user)


@router.post('/plans/{plan_id}/confirm')
def confirm(plan_id: int, data: RerouteConfirmIn, user=Depends(require('supervisor'))):
    return service.confirm(plan_id, data, user)


@router.patch('/belts/{belt_code}/capacity')
def update_capacity(belt_code: str, data: BeltCapacityIn, user=Depends(require('supervisor'))):
    return service.update_capacity(belt_code, data, user)
