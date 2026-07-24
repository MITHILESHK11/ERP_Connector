import logging
from adapters.base_adapter import BaseERPAdapter, ADAPTER_REGISTRY
from config.settings import get_settings

logger = logging.getLogger("adapters.registry")

# ---------------------------------------------------------------------------
# Guarded imports — adapters are stubs until Dev 2 / Dev 3 implement them.
# The server must start cleanly even when the adapter files are placeholders.
#
# Each adapter self-registers into ADAPTER_REGISTRY via the @register_adapter
# decorator on import (see adapters/base_adapter.py) — get_adapter() below no
# longer needs an if/elif branch per ERP. Adding a new ERP is: write the
# adapter file, decorate its class, add ONE import line here.
# ---------------------------------------------------------------------------
try:
    from adapters.xero import XeroAdapter  # noqa: F401 — import registers it
    _xero_available = True
except ImportError:
    _xero_available = False
    logger.warning("XeroAdapter could not be imported — adapters/xero.py is not yet implemented.")

try:
    from adapters.qbo import QBOAdapter  # noqa: F401 — import registers it
    _qbo_available = True
except ImportError:
    _qbo_available = False
    logger.warning("QBOAdapter could not be imported — adapters/qbo.py is not yet implemented.")

try:
    from adapters.mock import MockAdapter  # noqa: F401 — import registers it
    _mock_available = True
except ImportError:
    _mock_available = False
    logger.warning("MockAdapter could not be imported — adapters/mock.py is missing.")


# Friendlier errors for the two "implemented later by another dev" cases,
# kept identical to the previous if/elif version so existing behavior/tests
# don't change.
_NOT_IMPLEMENTED_MESSAGES = {
    "xero": "XeroAdapter is not yet implemented. Dev 2 must complete adapters/xero.py before Xero requests can be served.",
    "quickbooks": "QBOAdapter is not yet implemented. Dev 3 must complete adapters/qbo.py before QuickBooks requests can be served.",
    "mock": "MockAdapter is missing.",
}
_AVAILABILITY = {"xero": _xero_available, "quickbooks": _qbo_available, "qbo": _qbo_available, "mock": _mock_available}


def get_adapter() -> BaseERPAdapter:
    """
    Adapter registry — the single place that decides which ERP adapter to use.

    Reads ERP_TYPE from the application settings on every call (no caching),
    looks it up in ADAPTER_REGISTRY (populated by @register_adapter on each
    adapter class), instantiates it, logs the selection, and returns it.

    Returns:
        BaseERPAdapter: A concrete adapter instance for the configured ERP.

    Raises:
        ValueError: If ERP_TYPE is not a registered adapter name.
        NotImplementedError: If the adapter for the configured ERP has not
                             been implemented yet (stub file / import failed).
    """
    settings = get_settings()
    erp_type = settings.ERP_TYPE.lower()

    if erp_type not in ADAPTER_REGISTRY:
        raise ValueError(
            f"Unknown ERP_TYPE: {erp_type}. Supported values: {sorted(set(ADAPTER_REGISTRY.keys()) | {'xero', 'quickbooks', 'mock'})}"
        )

    if not _AVAILABILITY.get(erp_type, True):
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGES.get(erp_type, f"{erp_type} adapter is not available."))

    adapter_cls = ADAPTER_REGISTRY[erp_type]
    logger.info(f"Adapter resolved: {adapter_cls.__name__} (ERP_TYPE={erp_type})")
    return adapter_cls()

