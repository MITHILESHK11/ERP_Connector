import asyncio
import httpx

BASE_URL = "http://localhost:8000"

async def run_manual_routes_check():
    from token_manager import get_valid_token, get_tenant_id
    
    token = get_valid_token()
    tenant_id = get_tenant_id()
    
    headers = {
        "X-ERP-Token": token,
        "X-ERP-Tenant-Id": tenant_id
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        
        # Test 1 - Health
        r = await client.get(f"{BASE_URL}/healthz")
        print("Health:", r.json())
        
        # Test 2 - All invoices
        r = await client.get(f"{BASE_URL}/erp/invoices", headers=headers)
        data = r.json()
        print(f"All invoices: {data.get('count', 'error')} found")
        
        # Test 3 - Paid invoices
        r = await client.get(f"{BASE_URL}/erp/invoices?status=paid", headers=headers)
        data = r.json()
        print(f"Paid invoices: {data.get('count', 'error')} found")
        
        # Test 4 - Authorised invoices
        r = await client.get(f"{BASE_URL}/erp/invoices?status=authorised", headers=headers)
        data = r.json()
        print(f"Authorised invoices: {data.get('count', 'error')} found")
        
        # Test 5 - Bills
        r = await client.get(f"{BASE_URL}/erp/bills", headers=headers)
        data = r.json()
        print(f"Bills: {data.get('count', 'error')} found")
        
        # Test 6 - Accounts
        r = await client.get(f"{BASE_URL}/erp/accounts", headers=headers)
        data = r.json()
        

if __name__ == "__main__":
    asyncio.run(run_manual_routes_check())