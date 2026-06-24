import pytest
from utils.pagination import fetch_all_pages
from utils.errors import ERPConnectorError

@pytest.mark.anyio
async def test_pagination_single_page():
    # Return less than 1000 records on first page
    async def mock_fetch(page: int):
        assert page == 1
        return [{"id": i} for i in range(500)]
        
    results = await fetch_all_pages(mock_fetch)
    assert len(results) == 500


@pytest.mark.anyio
async def test_pagination_multiple_pages():
    pages = {
        1: [{"id": i} for i in range(1000)],
        2: [{"id": i} for i in range(1000)],
        3: [{"id": i} for i in range(250)],
    }
    
    async def mock_fetch(page: int):
        return pages.get(page, [])
        
    results = await fetch_all_pages(mock_fetch)
    assert len(results) == 2250


@pytest.mark.anyio
async def test_pagination_exact_1000():
    pages = {
        1: [{"id": i} for i in range(1000)],
        2: []
    }
    
    async def mock_fetch(page: int):
        return pages.get(page, [])
        
    results = await fetch_all_pages(mock_fetch)
    assert len(results) == 1000


@pytest.mark.anyio
async def test_pagination_safety_cap():
    async def mock_fetch(page: int):
        return [{"id": i} for i in range(1000)]
        
    with pytest.raises(ERPConnectorError) as exc_info:
        await fetch_all_pages(mock_fetch)
        
    assert exc_info.value.error_code == "INVALID_REQUEST"
    assert exc_info.value.http_status == 400
    assert "Result set exceeds 100,000 records" in exc_info.value.message
