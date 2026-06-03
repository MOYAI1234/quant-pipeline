from datetime import datetime
from copy import deepcopy
import uuid


class OrderManager:

    def __init__(self):
        self.orders = {}

    def create_order(self, order: dict) -> str:
        order_record = deepcopy(order)
        order_id = str(uuid.uuid4())[:8]
        order_record['id'] = order_id
        order_record['status'] = 'pending'
        order_record['created_at'] = datetime.now()
        self.orders[order_id] = order_record
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

    def snapshot(self) -> dict:
        return {
            'version': 1,
            'orders': [
                self._serialize_order(order)
                for order in self.orders.values()
            ],
        }

    def restore(self, snapshot: dict):
        if snapshot.get('version') != 1:
            raise ValueError('不支持的 OrderManager 状态版本')
        self.orders = {}
        for order in snapshot.get('orders', []):
            restored_order = self._deserialize_order(order)
            order_id = restored_order.get('id')
            if not order_id:
                raise ValueError('订单快照缺少 id 字段')
            self.orders[order_id] = restored_order

    def _serialize_order(self, order: dict) -> dict:
        serialized = deepcopy(order)
        for field in ('created_at', 'updated_at'):
            value = serialized.get(field)
            if isinstance(value, datetime):
                serialized[field] = value.isoformat()
        return serialized

    def _deserialize_order(self, order: dict) -> dict:
        restored = deepcopy(order)
        for field in ('created_at', 'updated_at'):
            value = restored.get(field)
            if isinstance(value, str) and value:
                restored[field] = datetime.fromisoformat(value)
        return restored
