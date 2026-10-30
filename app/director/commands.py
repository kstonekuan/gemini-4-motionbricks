"""Transport-independent shared command outcomes and ticket identity."""

from dataclasses import dataclass
from enum import Enum


class QueueRejection(Enum):
    FULL = "full"


class WithdrawalOutcome(Enum):
    WITHDRAWN = "withdrawn"
    DIFFERENT_VIEWER = "different_viewer"
    NOT_WAITING = "not_waiting"


@dataclass(frozen=True)
class InstructionTicket:
    id: str
    instruction: str
    submitted_by: str
