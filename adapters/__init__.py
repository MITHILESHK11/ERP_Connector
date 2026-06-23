import logging
from adapters.base_adapter import BaseERPAdapter
from config.settings import get_settings

logger = logging.getLogger("adapters.registry")

# ---------------------------------------------------------------------------
# Guarded imports — adapters are stubs until Dev 2 / Dev 3 implement them.
# The server must start cleanly even when the adapter files are placeholders.
# ---------------------------------------------------------------------------
try:
    from adapters.xero import XeroAdapter
    _xero_available = True
except ImportError:
    _xero_available = False
    logger.warning("XeroAdapter could not be imported — adapters/xero.py is not yet implemented.")

try:
    from adapters.qbo import QBOAdapter
    _qbo_available = True
except ImportError:
    _qbo_available = False
    logger.warning("QBOAdapter could not be imported — adapters/qbo.py is not yet implemented.")


def get_adapter() -> BaseERPAdapter:
    """
    Adapter registry — the single place that decides which ERP adapter to use.

    Reads ERP_TYPE from the application settings on every call (no caching),
    instantiates the matching adapter, logs the selection, and returns it.

    Returns:
        BaseERPAdapter: A concrete adapter instance for the configured ERP.

    Raises:
        ValueError: If ERP_TYPE is not 'xero' or 'quickbooks'.
        NotImplementedError: If the adapter for the configured ERP has not
                             been implemented yet (stub file detected).
    """
    settings = get_settings()
    erp_type = settings.ERP_TYPE  # already validated as 'xero' or 'quickbooks'

    if erp_type == "xero":
        if not _xero_available:
            raise NotImplementedError(
                "XeroAdapter is not yet implemented. "
                "Dev 2 must complete adapters/xero.py before Xero requests can be served."
            )
        logger.info("Adapter resolved: XeroAdapter (ERP_TYPE=xero)")
        return XeroAdapter()

    if erp_type == "quickbooks":
        if not _qbo_available:
            raise NotImplementedError(
                "QBOAdapter is not yet implemented. "
                "Dev 3 must complete adapters/qbo.py before QuickBooks requests can be served."
            )
        logger.info("Adapter resolved: QBOAdapter (ERP_TYPE=quickbooks)")
        return QBOAdapter()

    # This branch is only reachable if settings validation is bypassed externally
    raise ValueError(
        f"Unknown ERP_TYPE: {erp_type}. Supported values: xero, quickbooks"
    )
