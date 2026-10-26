# eisy-ai

eisy-ai is your AI companion for eisy. It can help with complex tasks such as:

- Creating sophisticated routines based on your devices, preferences, and plugins
- Running complex diagnostics using your system configuration and logs
- Investigating why something turned on or off seemingly randomly
- Supporting plans such as planning a new installation or a vacation

You will be using your own LLM/model and API Keys. As such, ensure that you have them ready before proceeding with the configuration.

# Configuration

`Configuration` is a JSON object that contains the necessary parameters for setting up your LLM provider, API key, and model preferences. 
With the exception of important file locations, you have great control over all configuration options.

# Example Configuration

This configuration uses Claude as the LLM provider for both home automation as well as generating plugins. You can simply replace the `${ANTHROPIC_API_KEY}` with your own API key and adjust the model as needed. 

**NOTE**:
- You do not need anything for `search engine` configuration, since Claude has its own tool
- Make sure you copy the whole JSON configuration block including the opening and closing triple backticks (```` ```json ... ``` ````)

````json
```json 
{
  "max_tool_set_switches_per_turn": 1,
  "search_engine": null,
  "search_engine_api_key": null,
  "mcp_server": false,
  "nucore_runtime": {
    "unified": {
      "enabled": true,
      "provider": "claude",
      "model": "claude-haiku-5-5",
      "api_key": "Replace_with_your_Anthropic_API_Key",
      "stream": true,
      "url": null,
      "max_turns": 20,
      "max_tokens": 64000,
      "cache_ttl": "5m",
      "max_iterations": 20,
      "history_token_budget": 20000,
      "fabrication_guard_mode": "log",
      "max_fabrication_retries": 1
    },
    "plugin_authoring": {
      "enabled": true,
      "provider": "claude",
      "model": "claude-sonnet-5-5",
      "api_key": "Replace_with_your_Anthropic_API_Key",
      "stream": true,
      "url": null,
      "max_turns": 20,
      "max_tokens": 64000,
      "cache_ttl": "5m",
      "max_iterations": 50,
      "history_token_budget": 20000,
      "fabrication_guard_mode": "log",
      "max_fabrication_retries": 1
    }
  }
}
``` 
````

# Explanation of Configuration Options

## Shape

```json
{
  "max_tool_set_switches_per_turn": 1,
  "search_engine": "brave",
  "search_engine_api_key": "${SEARCH_ENGINE_API_KEY}",
  "mcp_server": false,
  "nucore_runtime": {
    "unified": { "provider": "claude", "model": "...", "...": "..." },
    "plugin_authoring": { "provider": "claude", "model": "...", "...": "..." }
  }
}
```

Top level configuration options are global settings that apply to the entire system. `nucore_runtime` is required and must be a non-empty object. Each key inside `nucore_runtime` is a **profile** -- a named, independently-configured tool set. The loader itself is generic over any number of profiles with any names, but only two names currently have real tool-set wiring behind them: `unified` (the customer-facing tool set)
and `plugin_authoring` (the developer/plugin-authoring tool set). A profile with any other name loads and validates fine but isn't reachable by anything today.

## Top-level fields

| Field | Type | Default | Effect |
|---|---|---|---|
| `nucore_runtime` | object | *(required)* | Maps profile name → profile config (see below). Must contain at least one profile, and at least one must resolve to `enabled: true` (see `enabled` below) or loading raises `ValueError`. |
| `max_tool_set_switches_per_turn` | integer | `1` | Caps how many times one user turn may chain from one tool set into the other after a model-driven `switch_to_developer_mode`/`switch_to_customer_mode` call. Exceeding it returns an ordinary `{"error": ...}` tool result, not a crash. |
| `search_engine` | `"brave"` \| `"tavily"` | *(none)* | Web-search provider for `plugin_authoring`'s `search_web` tool (and `unified`'s, since this is shared by either tool set's discovery tools). Omitting it does **not** disable web search outright: when the resolved provider for a tool set is Claude, Claude's own native `web_search` server tool is used automatically instead, no second API key needed. For any other provider, omitting this means no web search capability at all for that tool set. Setting it explicitly always forces the Brave/Tavily fallback, even on Claude. |
| `search_engine_api_key` | string | *(none)* | API key for `search_engine`, is a placeholder for your API Key for either `brave` or `tavily`. Required for `search_engine` to actually take effect; `search_engine` with no key behaves the same as neither being set. |
| `mcp_server` | boolean | `false` | Exposes every tool eisy-ai has (both `unified` and `plugin_authoring`, whichever are `enabled`) to an external [MCP](https://modelcontextprotocol.io/) client over the network, bypassing the normal chat/LLM flow entirely -- useful for an IDE assistant or other MCP-native tool that wants to call eisy-ai's tools directly. Must be the literal boolean `true` to take effect; anything else (including omitting it) leaves it off. **Opens a TLS TCP listener on port 8260 with no application-level authentication at all (Phase 1 of this feature) -- anyone who can reach that port on your network gets the same tool access a logged-in session has, including `run_shell_command` and full device control.** Only enable this on a network you fully trust; see `design/mcp-server.md` in the `nucore-ai` repo for the full design and security tradeoffs. |
| any other key | -- | -- | Silently ignored -- never an error. This is also how a documentation-only key survives in a file format with no comment syntax; see "Documentation-only keys" below. |

## Per-profile fields (`nucore_runtime.<name>`)

| Field | Type | Default | Effect |
|---|---|---|---|
| `provider` | string | *(required)* | Which LLM backend this profile calls. Accepted values (case-insensitive, aliases shown): `claude`/`anthropic`, `openai`/`gpt`, `gemini`/`google`, `grok`/`xai`/`x.ai`, `llamacpp`/`llama_cpp`/`llama.cpp`. Empty/missing raises `ValueError`. |
| `model` | string | *(none)* | Passed straight through to the provider's API as the model identifier (e.g. `"claude-sonnet-5"`, `"gpt-5.6-luna"`). Not validated at load time -- an unknown model string just fails at call time with whatever error the provider's API returns. |
| `api_key` | string | *(none)* | placeholder for your API Key for the model. `llama.cpp` needs no real key -- it falls back to the literal string `"no-key"` if nothing else is set, since most llama.cpp servers run unauthenticated. |
| `url` | string | *(none)* | Custom base URL for the provider's API (e.g. a self-hosted llama.cpp server, or an OpenAI-compatible proxy). `null`/omitted uses the provider's own default endpoint. |
| `enabled` | boolean | `true` | Whether this tool set is reachable at all. `false` removes it from `enabled_profiles` without deleting the rest of its config -- the profile's settings stay in the file, just dormant. At least one profile across the whole file must end up enabled. |
| `max_iterations` | integer | `8` | Hard cap on tool-call rounds within one `AgenticLoop.run()` call for this tool set. Hitting it without a final answer returns a hardcoded "ran out of steps" message rather than looping forever. |
| `max_turns` | integer | `20` | How many past turns of this tool set's own conversation history are kept and replayed on each new call (older turns are dropped, oldest-first). Also used as this profile's `SessionStore` turn cap. |
| `max_tokens` | integer | *(provider-adapter default; typically `4096`)* | Requested max output tokens per LLM call. **Only forwarded to the API for `claude`, `gemini`, and `llamacpp` providers.** For `openai` and `grok`, this field is currently read but never sent -- see "Provider-specific caveats" below. |
| `temperature` | number | *(none; provider default applies)* | Sampling temperature. **Only forwarded for `claude` and `gemini`.** For `openai` and `grok`, silently not sent at all, regardless of what's configured here -- see "Provider-specific caveats" below. For `claude`, a model that has deprecated this parameter (confirmed as of this writing for `claude-sonnet-5` and `claude-haiku-5-5`, and likely the rest of the 5.5 family) gets a 400 on the first call per process and is automatically retried without it -- see `claude_adapter.py`'s `_no_temperature_models`. |
| `reasoning_effort` | string | *(none)* | Forwarded only to `openai`-family providers, and only when truthy (e.g. `"none"`, `"low"`). Some OpenAI reasoning-tier models reject function tools on the chat-completions endpoint unless this is explicitly set. No effect for any other provider. |
| `cache_ttl` | `"5m"` \| `"1h"` | *(none -- Anthropic's default 5-minute ephemeral cache)* | Prompt-cache breakpoint TTL. **Claude-only** -- silently has no effect for any other provider. `"1h"` costs 2x to write vs. 1.25x for `"5m"`, so it only pays off when turns in the same conversation are typically 5-60 minutes apart. Any other value raises `ValueError`. |
| `stream` | boolean | `false` | Whether this profile's responses stream token-by-token. Streaming only actually happens when the caller also supplied a live `StreamHandler` (always true when running via `run_unified_runtime.py`, in both REPL and WebSocket modes) -- with `stream: true` but no handler, this profile behaves as non-streaming regardless. |
| `history_token_budget` | integer | `20000` | Soft token budget this tool set's conversation history is compacted down toward before being replayed into a new call -- independent of `max_turns`, which caps by *turn count* rather than token count. |
| `fabrication_guard_mode` | `"off"` \| `"log"` \| `"block"` | `"log"` | How the agentic loop reacts when the model claims an action completed without having called a tool this turn. `"off"`: no check. `"log"`: detect and record a flag line in the prompt log, but never change what the customer sees. `"block"`: also inject a corrective nudge and force one more round (up to `max_fabrication_retries` times) instead of returning the flagged reply. Any other value raises `ValueError`. |
| `max_fabrication_retries` | integer | `1` | How many corrective retries `fabrication_guard_mode: "block"` gets before giving up and returning a hardcoded non-claim fallback instead of the model's (possibly false) claim. No effect in `"off"`/`"log"` mode. |
| `supports_system_role` | boolean | provider's own capability table (`true` for every provider currently listed) | Computed and stored on the normalized profile, but **not currently read by any adapter** -- every adapter already handles a `system`-role message its own way regardless of this flag. Setting it has no observable effect today; it's reserved from the original per-provider capability design. |
| any other key | -- | -- | Silently ignored, same as at the top level -- see "Documentation-only keys" below. |

# Local LLM Support
Support for local LLM is in the works.

# Example Models 
`claude-haiku-5-5`
`claude-sonnet-5-5`
`claude-haiku-4-5-20251001`
`gpt-5.6-luna`
`grok-4-fast`
`gemini-flash-latest`
