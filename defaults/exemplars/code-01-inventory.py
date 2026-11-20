"""A small inventory tracker with stock movements and reorder suggestions."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Item:
    sku: str
    name: str
    quantity: int = 0
    reorder_level: int = 5
    history: list[tuple[datetime, int, str]] = field(default_factory=list)


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self):
        self._items = {}

    def add_item(self, sku, name, reorder_level=5):
        if sku in self._items:
            raise ValueError(f"duplicate sku: {sku}")
        self._items[sku] = Item(sku, name, reorder_level=reorder_level)
        return self._items[sku]

    def receive(self, sku, amount, note="delivery"):
        if amount <= 0:
            raise ValueError("amount must be positive")
        item = self._items[sku]
        item.quantity += amount
        item.history.append((datetime.now(), amount, note))

    def ship(self, sku, amount, note="order"):
        item = self._items[sku]
        if amount > item.quantity:
            raise OutOfStock(f"{item.name}: wanted {amount}, have {item.quantity}")
        item.quantity -= amount
        item.history.append((datetime.now(), -amount, note))

    def low_stock(self):
        return sorted(
            (item for item in self._items.values() if item.quantity <= item.reorder_level),
            key=lambda item: item.quantity,
        )

    def movements_by_day(self, sku):
        totals = defaultdict(int)
        for moment, amount, _ in self._items[sku].history:
            totals[moment.date()] += amount
        return dict(totals)

    def suggest_reorder(self, sku, days=14):
        """Order enough to cover the average daily outflow for the given number of days."""
        shipped = [-amount for _, amount, _ in self._items[sku].history if amount < 0]
        if not shipped:
            return 0
        average = sum(shipped) / max(len(self.movements_by_day(sku)), 1)
        return max(round(average * days) - self._items[sku].quantity, 0)

    def stock_value(self, prices):
        """Total value of the stock on hand, given a price per sku; unknown skus count as zero."""
        return sum(item.quantity * prices.get(item.sku, 0.0) for item in self._items.values())

    def rename(self, sku, new_name):
        if not new_name.strip():
            raise ValueError("a name is required")
        self._items[sku].name = new_name.strip()

    def report(self):
        lines = [f"{'SKU':<10}{'Name':<24}{'Qty':>6}"]
        for item in sorted(self._items.values(), key=lambda item: item.sku):
            flag = "  (low)" if item.quantity <= item.reorder_level else ""
            lines.append(f"{item.sku:<10}{item.name:<24}{item.quantity:>6}{flag}")
        return "\n".join(lines)


if __name__ == "__main__":
    stock = Inventory()
    stock.add_item("A-100", "Notebook, ruled")
    stock.add_item("A-200", "Pencil, HB", reorder_level=20)
    stock.receive("A-100", 40)
    stock.receive("A-200", 100)
    stock.ship("A-100", 37)
    stock.ship("A-200", 30)
    print(stock.report())
    print("reorder:", [(item.sku, stock.suggest_reorder(item.sku)) for item in stock.low_stock()])
