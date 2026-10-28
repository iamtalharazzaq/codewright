from fastapi import APIRouter, FastAPI

app = FastAPI()
orders = APIRouter(prefix="/orders")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@orders.get("/{order_id}")
async def get_order(order_id: int) -> dict[str, int]:
    return {"id": order_id}


@orders.post("")
def create_order() -> dict[str, int]:
    return {"id": 1}


app.include_router(orders, prefix="/api")
