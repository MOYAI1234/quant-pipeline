from datetime import datetime
import uuid


class OrderManager:

    def __init__(self):
        self.orders = {}

    def create_order(self, order: dict) -> str:
        order_id = str(uuid.uuid4())[:8]
        order['id'] = order_id
        order['status'] = 'pending'
        order['created_at'] = datetime.now()
        self.orders[order_id] = order
        return order_id

    def update_status(self, order_id: str, status: str):
        if order_id in self.orders:
            self.orders[order_id]['status'] = status
            self.orders[order_id]['updated_at'] = datetime.now()

    def get_order(self, order_id: str) -> dict:
        return self.orders.get(order_id)

    def get_pending_orders(self) -> list:
        return [o for o in self.orders.values() if o.get('status') == 'pending']

    def get_all_orders(self) -> list:
        return list(self.orders.values())
