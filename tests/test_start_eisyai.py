"""start_eisyai._resolve_startup_notice -- the pure decision function behind
the "Eisy AI" startup notice (see EisyaiControllerNode.start()). Covers all
four (has_llm_key, mcp_server) combinations; the rest of start_eisyai()
(threading, SSL files, Polyglot wiring) has too many side effects to unit
test and isn't touched by this function at all.
"""

from __future__ import annotations

from start_eisyai import _resolve_startup_notice


def test_no_key_and_mcp_server_true_is_mcp_only_notice():
    runtime_config = {"mcp_server": True, "nucore_runtime": {"unified": {"provider": "claude"}}}
    notice = _resolve_startup_notice(runtime_config, env={})
    assert notice is not None
    assert "MCP-only mode" in notice
    assert "web chat is not available" in notice


def test_no_key_and_mcp_server_false_is_needs_a_key_notice():
    runtime_config = {"mcp_server": False, "nucore_runtime": {"unified": {"provider": "claude"}}}
    notice = _resolve_startup_notice(runtime_config, env={})
    assert notice is not None
    assert "MCP-only" not in notice
    assert "cannot start web chat or plugin authoring" in notice


def test_no_key_and_mcp_server_absent_is_also_needs_a_key_notice():
    runtime_config = {"nucore_runtime": {"unified": {"provider": "claude"}}}
    notice = _resolve_startup_notice(runtime_config, env={})
    assert notice is not None
    assert "cannot start web chat or plugin authoring" in notice


def test_inline_key_present_is_no_notice_regardless_of_mcp_server():
    runtime_config = {
        "mcp_server": True,
        "nucore_runtime": {"unified": {"provider": "claude", "api_key": "sk-ant-real"}},
    }
    assert _resolve_startup_notice(runtime_config, env={}) is None

    runtime_config["mcp_server"] = False
    assert _resolve_startup_notice(runtime_config, env={}) is None


def test_env_fallback_key_present_is_no_notice():
    runtime_config = {"mcp_server": True, "nucore_runtime": {"unified": {"provider": "openai"}}}
    notice = _resolve_startup_notice(runtime_config, env={"OPENAI_API_KEY": "sk-from-env"})
    assert notice is None


def test_no_provider_profiles_at_all_is_needs_a_key_notice():
    notice = _resolve_startup_notice({}, env={})
    assert notice is not None
    assert "cannot start web chat or plugin authoring" in notice
