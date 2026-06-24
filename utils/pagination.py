from typing import Callable, Awaitable, List, Any
from utils.errors import ERPConnectorError

async def fetch_all_pages(fetch_page: Callable[[int], Awaitable[List[Any]]]) -> List[Any]:
    """
    Loops through pages internally, calling fetch_page(page) starting at 1,
    until a page returns fewer than 1000 records. Merges and returns the results.
    
    If page count exceeds 100 pages, raises an ERPConnectorError.

    Usage example:
      # Xero usage:
      results = await fetch_all_pages(
        lambda page: xero_client.get(f"/Invoices?page={page}")
      )

      # QBO usage:
      results = await fetch_all_pages(
        lambda page: qbo_client.query(f"SELECT * FROM Invoice STARTPOSITION {(page-1)*1000+1} MAXRESULTS 1000")
      )
    """
    merged_list = []
    page = 1
    max_pages = 100

    while True:
        if page > max_pages:
            raise ERPConnectorError(
                error_code="INVALID_REQUEST",
                message="Result set exceeds 100,000 records. Apply stricter date filters.",
                http_status=400
            )

        records = await fetch_page(page)
        
        # If the page returns no records or is not a list, terminate loop
        if not records or not isinstance(records, list):
            break
            
        merged_list.extend(records)
        
        # Fewer than 1000 records signals the last page
        if len(records) < 1000:
            break
            
        page += 1

    return merged_list
