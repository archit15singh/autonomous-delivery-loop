"""Persist accepted orders and submit their background processing."""
from threading import Thread

from redis import Redis


class Orders:
    def __init__(self, host):
        self.store = Redis(host=host, decode_responses=True)

    def submit(self, quantity):
        if type(quantity) is not int or quantity < 1:
            return False
        self.store.set("adl:order:accepted", quantity)
        Thread(target=self.complete, args=(quantity,), daemon=True).start()
        return True

    def current(self):
        quantity = self.store.get("adl:order:accepted")
        return int(quantity) if quantity is not None else None

    def complete(self, quantity):
        self.store.set("adl:order:processed", quantity)
