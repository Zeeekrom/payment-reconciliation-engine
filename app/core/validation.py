"""Channel status normalisation (validation/normalisation) — Phase A, implemented by Evan.

Responsibility:
Translate each channel's own raw status into a unified NormalizedOutcome.

Note:
- This only judges the outcome expressed by a single event.
- It is not responsible for combining multiple events to compute an order's final status.
- Unrecognized statuses return UNKNOWN rather than letting the pipeline crash outright.
"""

from enum import Enum


class NormalizedOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


def _clean_status(raw_status: str) -> str:
    """Clean up a status string.

    Non-strings, empty strings, and whitespace-only strings are treated as an empty
    string, which each channel's normalisation function ultimately maps to UNKNOWN.
    """
    if not isinstance(raw_status, str):
        return ""

    return raw_status.strip()


def normalize_channel_a(raw_status: str) -> NormalizedOutcome:
    """Translate Channel A's raw status string into a NormalizedOutcome.

    Channel A is a synchronous channel; currently only explicit success and explicit
    failure are defined. No PENDING status is defined.
    """
    status = _clean_status(raw_status)

    status_mapping = {
        "微信订单支付成功": NormalizedOutcome.SUCCESS,
        "微信订单支付失败": NormalizedOutcome.FAILED,
    }

    return status_mapping.get(status, NormalizedOutcome.UNKNOWN)


def normalize_channel_b(raw_status: str) -> NormalizedOutcome:
    """Translate Channel B's raw transaction status into a NormalizedOutcome.

    Handling policy used in this project:
    - SUCCESS: payment succeeded
    - NOTPAY: not yet paid, payment may still proceed, so treated as PENDING
    - USERPAYING: user is in the process of paying, treated as PENDING
    - CLOSED, REVOKED, PAYERROR: the payment flow can no longer proceed, treated as FAILED
    - REFUND: refund status is not handled by the current version, so treated as UNKNOWN
    """
    status = _clean_status(raw_status).upper()

    status_mapping = {
        "SUCCESS": NormalizedOutcome.SUCCESS,
        "NOTPAY": NormalizedOutcome.PENDING,
        "USERPAYING": NormalizedOutcome.PENDING,
        "CLOSED": NormalizedOutcome.FAILED,
        "REVOKED": NormalizedOutcome.FAILED,
        "PAYERROR": NormalizedOutcome.FAILED,

        # Refunds are out of scope for the current version of the state machine.
        # A refund must not be mistakenly interpreted as an ordinary payment failure.
        "REFUND": NormalizedOutcome.UNKNOWN,
    }

    return status_mapping.get(status, NormalizedOutcome.UNKNOWN)


def normalize_channel_c(raw_status: str) -> NormalizedOutcome:
    """Translate Channel C's raw status string into a NormalizedOutcome.

    Channel C is deliberately used to test unknown status codes.
    All unrecognized statuses uniformly return UNKNOWN.
    """
    status = _clean_status(raw_status).upper()

    status_mapping = {
        "SUCCESS": NormalizedOutcome.SUCCESS,
        "FAILED": NormalizedOutcome.FAILED,
        "FAIL": NormalizedOutcome.FAILED,
        "PENDING": NormalizedOutcome.PENDING,
        "PROCESSING": NormalizedOutcome.PENDING,
    }

    return status_mapping.get(status, NormalizedOutcome.UNKNOWN)
