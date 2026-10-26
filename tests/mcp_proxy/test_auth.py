from __future__ import annotations

import pytest

from mcp_proxy.auth import AllowAllAuthHook


@pytest.mark.asyncio
async def test_allow_all_auth_hook_allows_everything():
    hook = AllowAllAuthHook()
    # The real contract takes a Starlette Request; None stands in fine here
    # since AllowAllAuthHook never inspects its argument -- that's the point.
    assert await hook.authenticate(None) is True
