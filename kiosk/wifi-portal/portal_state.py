"""Runtime data owned by one captive portal server."""

import threading
from _thread import LockType
from dataclasses import dataclass, field

from portal_config import PortalConfig
from portal_types import WifiNetwork


@dataclass
class PortalState:
    config: PortalConfig
    cached_networks: list[WifiNetwork] = field(default_factory=list)
    is_online: bool = False
    hotspot_active: bool = False
    stopping: bool = False
    lock: LockType = field(default_factory=threading.Lock)
    operation_lock: LockType = field(default_factory=threading.Lock)
