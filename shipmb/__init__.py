"""ShipMB command/API alias for ShipMBLang."""

import shipmblang as _language

__all__ = _language.__all__


def __getattr__(name):
    return getattr(_language, name)


def __dir__():
    return sorted(set(globals()) | set(__all__))
