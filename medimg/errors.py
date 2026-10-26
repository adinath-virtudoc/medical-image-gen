"""User-facing errors: every one carries a cause and a fix."""
from __future__ import annotations


class MedimgError(Exception):
    def __init__(self, cause: str, fix: str = ""):
        super().__init__(cause)
        self.cause = cause
        self.fix = fix

    def __str__(self) -> str:
        return f"{self.cause} Fix: {self.fix}" if self.fix else self.cause


class Unsupported(MedimgError): ...
class Blocked(MedimgError): ...
class Invalid(MedimgError): ...
class Busy(MedimgError): ...
class NotFound(MedimgError): ...
class ModelUnavailable(MedimgError): ...
class Cancelled(MedimgError):
    def __init__(self, cause: str = "Generation was cancelled.", fix: str = ""):
        super().__init__(cause, fix)
