"""Thread-safe reservation ledger for AI query budgets."""

from dataclasses import dataclass
from decimal import Decimal
from threading import Lock
from uuid import UUID, uuid4


class AIBudgetExceeded(RuntimeError):  # noqa: N818
    """Raised before provider invocation when an AI budget would be exceeded."""


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    id: UUID
    amount_usd: Decimal


class AIBudgetLedger:
    def __init__(
        self,
        limit_usd: Decimal,
        initial_spent_usd: Decimal = Decimal("0"),
    ) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = max(initial_spent_usd, Decimal("0"))
        self.reserved_usd = Decimal("0")
        self._reservations: dict[UUID, Decimal] = {}
        self._lock = Lock()

    def reserve(self, amount_usd: Decimal) -> BudgetReservation:
        amount = max(amount_usd, Decimal("0"))
        with self._lock:
            projected = self.spent_usd + self.reserved_usd + amount
            if projected > self.limit_usd:
                raise AIBudgetExceeded(
                    f"AI budget exceeded: projected ${projected} "
                    f"> ${self.limit_usd}"
                )
            reservation = BudgetReservation(uuid4(), amount)
            self._reservations[reservation.id] = amount
            self.reserved_usd += amount
            return reservation

    def settle(
        self,
        reservation: BudgetReservation,
        actual_usd: Decimal,
    ) -> None:
        with self._lock:
            held = self._reservations.pop(reservation.id)
            self.reserved_usd -= held
            self.spent_usd += max(actual_usd, Decimal("0"))

    def release(self, reservation: BudgetReservation) -> None:
        with self._lock:
            held = self._reservations.pop(
                reservation.id,
                Decimal("0"),
            )
            self.reserved_usd -= held
