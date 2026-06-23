from abc import ABC, abstractmethod

class BaseERPAdapter(ABC):
    """
    Abstract Base Class defining the interface for all ERP Adapters (e.g. XeroAdapter, QBOAdapter).
    
    All methods must be asynchronous since all upstream ERP API calls involve I/O operations.
    Every adapter implementation must subclass this BaseERPAdapter and implement all abstract methods.
    The implementations should accept raw inputs, query the respective ERP, normalize the output,
    and return the data formatted as standard dictionaries matching the agreed Pydantic models.
    """

    @abstractmethod
    async def get_invoices(self, token: str, tenant_id: str, from_date: str = None, 
                           to_date: str = None, status: str = None) -> list[dict]:
        """
        Fetch a list of invoices from the ERP and normalize them.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            from_date (str, optional): ISO 8601 date to filter invoices created on or after this date.
            to_date (str, optional): ISO 8601 date to filter invoices created on or before this date.
            status (str, optional): Status filter (draft, authorised, paid, voided).

        Returns:
            list[dict]: A list of dictionaries matching the NormalizedInvoice Pydantic schema.
        """
        pass

    @abstractmethod
    async def get_invoice(self, token: str, tenant_id: str, invoice_id: str) -> dict:
        """
        Fetch details of a single invoice from the ERP by its ID and normalize it.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            invoice_id (str): The unique invoice ID in the ERP system.

        Returns:
            dict: A dictionary matching the NormalizedInvoice Pydantic schema.
        """
        pass

    @abstractmethod
    async def get_bills(self, token: str, tenant_id: str, from_date: str = None, 
                        to_date: str = None) -> list[dict]:
        """
        Fetch a list of bills (purchase invoices) from the ERP and normalize them.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            from_date (str, optional): ISO 8601 date to filter bills created on or after this date.
            to_date (str, optional): ISO 8601 date to filter bills created on or before this date.

        Returns:
            list[dict]: A list of dictionaries matching the NormalizedBill Pydantic schema.
        """
        pass

    @abstractmethod
    async def get_contacts(self, token: str, tenant_id: str, 
                           contact_type: str = None) -> list[dict]:
        """
        Fetch a list of contacts (customers and/or suppliers) from the ERP and normalize them.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            contact_type (str, optional): Filter type ('customer' or 'supplier').

        Returns:
            list[dict]: A list of dictionaries matching the NormalizedContact Pydantic schema.
        """
        pass

    @abstractmethod
    async def get_accounts(self, token: str, tenant_id: str) -> list[dict]:
        """
        Fetch the chart of accounts from the ERP and normalize them.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.

        Returns:
            list[dict]: A list of dictionaries matching the NormalizedAccount Pydantic schema.
        """
        pass

    @abstractmethod
    async def create_invoice(self, token: str, tenant_id: str, data: dict) -> dict:
        """
        Create a new customer invoice in the ERP.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            data (dict): The invoice details (matching NormalizedInvoice input payload).

        Returns:
            dict: The created invoice details mapped to the NormalizedInvoice Pydantic schema.
        """
        pass

    @abstractmethod
    async def create_bill(self, token: str, tenant_id: str, data: dict) -> dict:
        """
        Create a new supplier bill in the ERP.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            data (dict): The bill details (matching NormalizedBill input payload).

        Returns:
            dict: The created bill details mapped to the NormalizedBill Pydantic schema.
        """
        pass

    @abstractmethod
    async def create_contact(self, token: str, tenant_id: str, data: dict) -> dict:
        """
        Create a new contact in the ERP.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            data (dict): The contact details (matching NormalizedContact input payload).

        Returns:
            dict: The created contact details mapped to the NormalizedContact Pydantic schema.
        """
        pass

    @abstractmethod
    async def record_payment(self, token: str, tenant_id: str, data: dict) -> dict:
        """
        Record a payment against an invoice or a bill in the ERP.
        
        Args:
            token (str): The OAuth 2.0 access token.
            tenant_id (str): The tenant/realm/organisation identifier.
            data (dict): The payment data containing the payment amount, date, and reference to the invoice/bill.

        Returns:
            dict: Details of the recorded payment, normalized to the ERP-specific payment schema representation.
        """
        pass
