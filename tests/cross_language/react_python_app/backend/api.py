"""FastAPI backend — orders and users endpoints."""
from fastapi import APIRouter

router = APIRouter()


class OrderModel:
    """Shared contract: matches OrderDTO on the frontend."""
    id: str
    user_id: str
    items: list
    total: float


class UserModel:
    """Shared contract: matches UserDTO on the frontend."""
    id: str
    name: str
    email: str


@router.get('/api/orders')
def get_orders():
    return []


@router.post('/api/orders')
def create_order(payload: dict):
    return {"id": "ord_001", "total": 42.0}


@router.get('/api/users')
def get_users():
    return []


@router.get('/api/users/{user_id}')
def get_user(user_id: str):
    return {"id": user_id, "name": "Alice"}
