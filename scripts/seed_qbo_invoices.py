import asyncio
import httpx

QBO_SANDBOX = "https://sandbox-quickbooks.api.intuit.com"
TOKEN = "your_token_here"        # replace manually each run
REALM_ID = "your_realm_id_here"  # replace manually each run
MINOR = "75"

async def create_test_invoice(session: httpx.AsyncClient, i: int):
    url = f"{QBO_SANDBOX}/v3/company/{REALM_ID}/invoice?minorversion={MINOR}"
    body = {
        "Line": [{
            "Amount": 100.00,
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {
                "ItemRef": {"value": "1"},
                "Qty": 1,
                "UnitPrice": 100.00,
            }
        }],
        "CustomerRef": {"value": "1"},
        "TxnDate": "2026-01-01",
        "DueDate": "2026-02-01",
        "DocNumber": f"TEST-BULK-{i:04d}",
    }
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    r = await session.post(url, json=body, headers=headers)
    if r.status_code == 200:
        print(f"Created invoice {i}")
    else:
        print(f"Failed invoice {i}: {r.status_code} {r.text[:100]}")

async def main():
    async with httpx.AsyncClient(timeout=30.0) as session:
        # Create 50 invoices at a time to avoid rate limits
        for batch_start in range(0, 200, 50):
            tasks = [create_test_invoice(session, i) 
                     for i in range(batch_start, batch_start + 50)]
            await asyncio.gather(*tasks)
            await asyncio.sleep(2)  # Respect rate limits

if __name__ == "__main__":
    asyncio.run(main())
