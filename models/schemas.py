from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime

# ==========================================
# LINE ITEM SCHEMAS
# ==========================================

class InvoiceLineItem(BaseModel):
    description: str = Field(
        ..., 
        description="Line item description. Xero=Description, QBO=Description"
    )
    quantity: float = Field(
        ..., 
        description="Line item quantity. Xero=Quantity, QBO=Qty"
    )
    unit_amount: int = Field(
        ..., 
        description="Unit amount in smallest currency unit (e.g. cents/paise). Xero=UnitAmount, QBO=UnitPrice"
    )
    account_code: str = Field(
        ..., 
        description="GL Account code. Xero=AccountCode, QBO=AccountRef.value"
    )


class BillLineItem(BaseModel):
    description: str = Field(
        ..., 
        description="Line item description. Xero=Description, QBO=Description"
    )
    quantity: float = Field(
        ..., 
        description="Line item quantity. Xero=Quantity, QBO=Qty"
    )
    unit_amount: int = Field(
        ..., 
        description="Unit amount in smallest currency unit (e.g. cents/paise). Xero=UnitAmount, QBO=UnitPrice"
    )
    account_code: str = Field(
        ..., 
        description="GL Account code. Xero=AccountCode, QBO=AccountRef.value"
    )

# ==========================================
# SCHEMA 1 - NormalizedInvoice
# ==========================================

class NormalizedInvoice(BaseModel):
    id: str = Field(
        ..., 
        description="Unique identifier for the invoice. Xero=InvoiceID, QBO=Id"
    )
    reference_number: str = Field(
        ..., 
        description="Invoice reference/number. Xero=InvoiceNumber, QBO=DocNumber"
    )
    date: str = Field(
        ..., 
        description="Invoice date in ISO 8601 (YYYY-MM-DD). Xero=Date, QBO=TxnDate"
    )
    due_date: str = Field(
        ..., 
        description="Invoice due date in ISO 8601 (YYYY-MM-DD). Xero=DueDate, QBO=DueDate"
    )
    amount: int = Field(
        ..., 
        description="Total invoice amount in smallest currency unit (e.g. cents/paise). Xero=Total, QBO=TotalAmt"
    )
    currency: str = Field(
        ..., 
        description="ISO 4217 Currency Code. Xero=CurrencyCode, QBO=CurrencyRef"
    )
    status: Literal["draft", "authorised", "paid", "voided"] = Field(
        ..., 
        description="Normalized invoice status. Xero=Status, QBO=status"
    )
    contact_id: str = Field(
        ..., 
        description="Associated customer ID. Xero=Contact.ContactID, QBO=CustomerRef.value"
    )
    line_items: List[InvoiceLineItem] = Field(
        ..., 
        description="Collection of line items on this invoice. Xero=LineItems, QBO=Line"
    )

# ==========================================
# SCHEMA 2 - NormalizedBill
# ==========================================

class NormalizedBill(BaseModel):
    id: str = Field(
        ..., 
        description="Unique identifier for the bill. Xero=InvoiceID, QBO=Id"
    )
    bill_number: str = Field(
        ..., 
        description="Bill reference number. Xero=InvoiceNumber, QBO=DocNumber"
    )
    date: str = Field(
        ..., 
        description="Bill date in ISO 8601 (YYYY-MM-DD). Xero=Date, QBO=TxnDate"
    )
    due_date: str = Field(
        ..., 
        description="Bill due date in ISO 8601 (YYYY-MM-DD). Xero=DueDate, QBO=DueDate"
    )
    amount: int = Field(
        ..., 
        description="Total bill amount in smallest currency unit (e.g. cents/paise). Xero=Total, QBO=TotalAmt"
    )
    currency: str = Field(
        ..., 
        description="ISO 4217 Currency Code. Xero=CurrencyCode, QBO=CurrencyRef"
    )
    status: Literal["draft", "authorised", "paid", "voided"] = Field(
        ..., 
        description="Normalized bill status. Xero=Status, QBO=status"
    )
    supplier_id: str = Field(
        ..., 
        description="Associated vendor/supplier ID. Xero=Contact.ContactID, QBO=VendorRef.value"
    )
    line_items: List[BillLineItem] = Field(
        ..., 
        description="Collection of line items on this bill. Xero=LineItems, QBO=Line"
    )

# ==========================================
# SCHEMA 3 - NormalizedContact
# ==========================================

class NormalizedContact(BaseModel):
    id: str = Field(
        ..., 
        description="Unique identifier for the contact. Xero=ContactID, QBO=Id"
    )
    name: str = Field(
        ..., 
        description="Name of the contact. Xero=Name, QBO=DisplayName"
    )
    email: Optional[str] = Field(
        None, 
        description="Email address. Xero=EmailAddress, QBO=PrimaryEmailAddr.Address"
    )
    phone: Optional[str] = Field(
        None, 
        description="Phone number. Xero=Phones (where PhoneType=DEFAULT), QBO=PrimaryPhone.FreeFormNumber"
    )
    type: Literal["customer", "supplier"] = Field(
        ..., 
        description="Normalized contact type. Xero=IsCustomer/IsSupplier flags, QBO=Mapped from Customer vs Vendor resource"
    )
    address: Optional[str] = Field(
        None, 
        description="Normalized billing or physical address. Xero=Addresses (where AddressType=POSTAL), QBO=BillAddr/ShipAddr"
    )

# ==========================================
# SCHEMA 4 - NormalizedAccount
# ==========================================

class NormalizedAccount(BaseModel):
    id: str = Field(
        ..., 
        description="Unique identifier for the account. Xero=AccountID, QBO=Id"
    )
    code: str = Field(
        ..., 
        description="General Ledger Code. Xero=Code, QBO=AcctNum"
    )
    name: str = Field(
        ..., 
        description="Account name. Xero=Name, QBO=Name"
    )
    type: str = Field(
        ..., 
        description="Type of the account (asset, liability, etc.). Xero=Type, QBO=AccountType"
    )
    tax_type: Optional[str] = Field(
        None, 
        description="Tax/GST/VAT settings mapping. Xero=TaxType, QBO=TaxCodeRef.value"
    )
    currency_code: Optional[str] = Field(
        None, 
        description="Base currency for this GL account. Xero=CurrencyCode, QBO=CurrencyRef.value"
    )

# ==========================================
# SCHEMA 5 - ErrorResponse
# ==========================================

class ErrorResponse(BaseModel):
    success: Literal[False] = Field(
        False, 
        description="Indicates query success status, always False in error scenarios"
    )
    error_code: str = Field(
        ..., 
        description="High level unified error code (e.g., TOKEN_EXPIRED, INVALID_REQUEST)"
    )
    message: str = Field(
        ..., 
        description="User-friendly error explanation"
    )
    erp: str = Field(
        ..., 
        description="Identifies the upstream ERP targeted (xero or quickbooks)"
    )
    timestamp: str = Field(
        ..., 
        description="UTC Timestamp of the error occurrence in ISO 8601 format"
    )
