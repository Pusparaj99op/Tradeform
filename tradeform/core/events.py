"""
Event system for module communication.
Simple pub/sub pattern for decoupled architecture.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Callable
from datetime import datetime
from enum import Enum


class EventType(Enum):
    """Types of events in the system."""
    # Connection events
    MT5_CONNECTED = "mt5_connected"
    MT5_DISCONNECTED = "mt5_disconnected"
    OLLAMA_CONNECTED = "ollama_connected"
    OLLAMA_DISCONNECTED = "ollama_disconnected"

    # Market events
    NEW_TICK = "new_tick"
    NEW_CANDLE = "new_candle"

    # AI events
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETE = "analysis_complete"
    NEW_SIGNAL = "new_signal"

    # Trade events
    TRADE_REQUESTED = "trade_requested"
    TRADE_EXECUTED = "trade_executed"
    TRADE_CLOSED = "trade_closed"
    TRADE_MODIFIED = "trade_modified"
    TRADE_REJECTED = "trade_rejected"

    # Risk events
    RISK_ALERT = "risk_alert"
    KILL_SWITCH = "kill_switch"
    DRAWDOWN_WARNING = "drawdown_warning"

    # System events
    LOG = "log"
    ERROR = "error"


@dataclass
class Event:
    """An event in the system."""
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self):
        return f"[{self.timestamp}] {self.type.value}: {self.data}"


class EventBus:
    """Simple event bus for pub/sub communication between modules."""

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._history: List[Event] = []
        self._max_history = 100

    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb != callback
            ]

    def emit(self, event: Event):
        """Emit an event to all subscribers."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        callbacks = self._subscribers.get(event.type, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                # Don't let one subscriber crash others
                pass

    def emit_simple(self, event_type: EventType, **data):
        """Convenience method to emit an event with keyword args."""
        self.emit(Event(type=event_type, data=data))

    def get_history(self, event_type: EventType = None, limit: int = 20) -> List[Event]:
        """Get recent event history, optionally filtered by type."""
        if event_type:
            filtered = [e for e in self._history if e.type == event_type]
        else:
            filtered = self._history
        return filtered[-limit:]
