"""Data exchanged by network operations, handlers and page rendering."""

from typing import TypedDict


class WifiNetwork(TypedDict):
    ssid: str
    signal: int
    security: str


class ConnectionStatus(TypedDict):
    connected: bool
    ssid: str
    ip: str
    internet: bool
