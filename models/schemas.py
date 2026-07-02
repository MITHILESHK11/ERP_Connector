from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
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


# ==========================================
# WRITE REQUEST VALIDATION SCHEMAS
# ==========================================

class LineItem(BaseModel):
    description: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    unit_amount: int = Field(..., gt=0)
    account_code: str = Field(...)
    tax_type: Optional[str] = None


class CreateInvoiceRequest(BaseModel):
    contact_id: str = Field(...)
    date: str = Field(...)
    due_date: str = Field(...)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    line_items: List[LineItem] = Field(..., min_length=1)

    @field_validator("date", "due_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        import datetime
        try:
            datetime.datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format and be a valid calendar date.")
        return v

    @model_validator(mode="after")
    def validate_dates(self):
        import datetime
        try:
            d1 = datetime.datetime.strptime(self.date, "%Y-%m-%d")
            d2 = datetime.datetime.strptime(self.due_date, "%Y-%m-%d")
            if d2 < d1:
                raise ValueError("due_date must be greater than or equal to date")
        except ValueError as e:
            raise ValueError(str(e))
        return self


class CreateBillRequest(BaseModel):
    supplier_id: str = Field(...)
    date: str = Field(...)
    due_date: str = Field(...)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    line_items: List[LineItem] = Field(..., min_length=1)

    @field_validator("date", "due_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        import datetime
        try:
            datetime.datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format and be a valid calendar date.")
        return v

    @model_validator(mode="after")
    def validate_dates(self):
        import datetime
        try:
            d1 = datetime.datetime.strptime(self.date, "%Y-%m-%d")
            d2 = datetime.datetime.strptime(self.due_date, "%Y-%m-%d")
            if d2 < d1:
                raise ValueError("due_date must be greater than or equal to date")
        except ValueError as e:
            raise ValueError(str(e))
        return self


class CreateContactRequest(BaseModel):
    name: str = Field(...)
    email: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    phone: Optional[str] = None
    type: Literal["customer", "supplier"] = Field(...)


class RecordPaymentRequest(BaseModel):
    invoice_id: str = Field(...)
    amount: int = Field(..., gt=0)
    date: str = Field(...)
    account_code: str = Field(...)

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        import datetime
        try:
            datetime.datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format and be a valid calendar date.")
        return v


class NormalizedPayment(BaseModel):
    id: str = Field(
        ..., 
        description="Unique identifier for the payment. Xero=PaymentID, QBO=Id"
    )
    invoice_id: str = Field(
        ..., 
        description="Associated invoice or bill ID. Xero=Invoice.InvoiceID, QBO=InvoiceRef.value"
    )
    amount: int = Field(
        ..., 
        description="Payment amount in smallest currency unit (e.g. cents/paise). Xero=Amount, QBO=TotalAmt"
    )
    date: str = Field(
        ..., 
        description="Payment date in ISO 8601 (YYYY-MM-DD). Xero=Date, QBO=TxnDate"
    )
    account_code: str = Field(
        ..., 
        description="GL Account code or bank account reference. Xero=Account.Code, QBO=DepositToAccountRef.value"
    )


