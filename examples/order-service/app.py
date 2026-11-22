"""An order API served by the factory's Bottle profile."""
import os

from bottle import Bottle, request, response

from orders import Orders


app = Bottle()
orders = Orders(os.environ["ADL_REDIS_HOST"])


@app.get("/_revision")
def identity():
    return {"revision": os.environ["ADL_REVISION"], "deployment": os.environ["ADL_DEPLOYMENT"]}


@app.post("/orders")
def submit_order():
    body = request.json
    quantity = body.get("quantity") if isinstance(body, dict) else None
    if not orders.submit(quantity):
        response.status = 422
        return {"error": "quantity must be positive"}
    response.status = 202
    return {"status": "accepted"}


@app.get("/orders")
def current_order():
    quantity = orders.current()
    return {"quantity": quantity}


if __name__ == "__main__":
    app.run(host=os.environ["ADL_HOST"], port=int(os.environ["PORT"]), quiet=True)
