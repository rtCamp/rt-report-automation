"""Sanity checks for the shared fixtures in `conftest.py`."""

import httpx

from app.frappe.service import FrappeService


async def test_mock_http_serves_frappe_requests(mock_http):
	requests = mock_http(
		lambda _request: httpx.Response(200, json={"data": [{"name": "PROJ-1"}]}),
	)

	projects = await FrappeService().get_projects_by_manager_email("pm@test.com")

	assert projects == [{"name": "PROJ-1"}]
	assert len(requests) == 1
	assert requests[0].url.host == "frappe.test"
	assert requests[0].url.path == "/api/resource/Project"
