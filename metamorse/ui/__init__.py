"""On-screen feedback. Implements `core.Observer`; the core never imports it."""
from .popup import PopupObserver
from .render import Row, rows

__all__ = ["PopupObserver", "Row", "rows"]
