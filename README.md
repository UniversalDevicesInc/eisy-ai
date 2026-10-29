# eisy-ai

eisy-ai is your AI companion for eisy. You talk to it in plain language. What it can actually do
depends on which of its two modes is active:

- **Customer mode** — control and understand your smart home: devices, scenes, routines,
  plugins, and day-to-day troubleshooting.
- **Developer mode** — build, test, and publish your own eisy plugins: researching a device's
  API, generating a working plugin, debugging it in VS Code, and pushing it to GitHub.

Every conversation starts in customer mode. This document starts with configuration (do this
first), then covers both modes and — since it's easy to miss — how to actually get from one to
the other.

---

## Configuration

eisy-ai calls out to your own LLM provider, so before you use it you'll need that provider's API
key in hand. Configuration itself is one JSON object, covering two independently-configured
profiles — `unified` (customer mode) and `plugin_authoring` (developer mode) — each with its own
provider, model, and settings. Outside of a few file-location fields, you're free to configure
each profile differently (e.g. a faster/cheaper model for everyday customer requests, a stronger
one for plugin authoring).

Here's a working example using Claude for both modes — replace
`Replace_with_your_Anthropic_API_Key` with your own key and adjust the model names as needed. You
don't need to configure anything for web search: when the provider is Claude, its own built-in
search tool is used automatically in either mode, and when customer mode's provider is
`openai-responses` (see below), OpenAI's own built-in search tool is used automatically there too.

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

A few fields worth knowing up front:

| Field | What it does |
|---|---|
| `provider` | Which LLM backend that profile calls: `claude`, `openai`, `openai-responses`, `gemini`, `grok`, or a local `llamacpp` server. See the `openai-responses` note below. |
| `model` | The exact model id passed to that provider. |
| `api_key` | Your API key for that provider (not needed for an unauthenticated local `llamacpp` server). |
| `enabled` | Turns a profile on or off without deleting its settings. At least one profile must stay enabled. |
| `url` | Point at a self-hosted or proxied endpoint instead of the provider's default. |
| `search_engine` / `search_engine_api_key` | Only needed for a provider without its own built-in search (every provider except Claude, and except `openai-responses` in customer mode), or to force Brave/Tavily search instead of a provider's built-in search. |
| `max_tool_set_switches_per_turn` | Caps how many times one message can bounce between customer and developer mode automatically — see "Switching between modes" below. |
| `mcp_server` | Off (`false`) by default. See the warning below before turning it on. |

> **`mcp_server: true` opens a network port.** Turning this on lets an external MCP client call
> eisy-ai's tools directly over the network instead of through ordinary chat — see "Using MCP"
> below for what that means, what it requires, and how to connect one. Leave this `false` (or
> omit it) unless you specifically want that, which is the default.

> **`openai-responses` is a second way to use OpenAI, for reasoning-tier models.** Plain `openai`
> talks to OpenAI's older `/v1/chat/completions` endpoint; `openai-responses` talks to OpenAI's
> newer `/v1/responses` endpoint instead. It's the same OpenAI account and the same API key as
> plain `openai` — only the endpoint and request shape differ. The reason it exists: some of
> OpenAI's reasoning models (the `o`-series and newer reasoning-tier `gpt-5`-family models) refuse
> to use function-calling tools at all on `/v1/chat/completions`, no matter what settings are
> tried, which breaks every eisy-ai capability that depends on tool calls. `/v1/responses` is
> OpenAI's own fix for that. Use plain `openai` normally; switch a profile to `openai-responses`
> only if you've hit that specific tool-rejection behavior with a reasoning model and want to keep
> using it anyway.

This covers the common case. For the complete field-by-field reference — every option, its
default, and provider-specific quirks (which fields each provider actually honors, prompt-cache
behavior, the fabrication-guard retry mechanism, and more) — see `POLYGLOT_CONFIG.md` in this
same directory.

---

## Using MCP (Model Context Protocol)

[MCP](https://modelcontextprotocol.io/) lets an external client — Claude Desktop, an IDE
assistant, or any other MCP-capable tool — call eisy-ai's tools directly over the network,
bypassing ordinary chat entirely. Set `mcp_server: true` in your config (see Configuration above)
to turn this on.

### Prerequisites

- **`mcp_server: true`** in your config.
- **Your eisy's own real login.** MCP access requires signing in with the same username/password
  that already protects this device's web UI and REST API, via a standard OAuth 2.1 flow — there
  is no unauthenticated access, and no separate "MCP password" to set up.
- **"Allow Unrestricted ISY Access by Node Server" must be enabled for this node server.** This is
  a one-time setting in this node server's own configuration screen (not in the JSON config
  above). MCP's sign-in step needs a connection to the hub that bypasses the normal plugin-to-ISY
  relay every other eisy-ai feature uses, and that connection is exactly what this permission
  gates — without it, sign-in can never complete, no matter how many times it's retried. If this
  is the problem, eisy-ai's own logs will say "ISY access not authorized."
- **No LLM provider API key is required.** MCP tool access works even with none configured at
  all — see "If no API key is configured" below for what that means for web chat specifically.

### Connecting a client

Using Claude Desktop as the concrete example (other MCP clients follow the same shape):

1. Add a remote MCP server pointed at your eisy's address, e.g. `https://eisy.local:8260`.
2. The client handles OAuth discovery and registration automatically and presents a login form —
   sign in with your eisy's own username and password (see Prerequisites above).
3. Once signed in, every tool from whichever profiles are enabled in your config (`unified`,
   `plugin_authoring`, or both) becomes available to that client, the same access a logged-in chat
   session already has.

### What's deliberately unavailable

Real device and plugin **deletions always come back as a preview only over MCP, never actually
executed**, regardless of what confirmation is sent — by design, independent of login status. See
`design/mcp-server.md` in the `nucore-ai` repo for the full design and its threat model.

### If no API key is configured

MCP tool access works fully either way. Web chat and plugin authoring don't — they need an LLM
provider API key, which MCP itself never uses. With `mcp_server: true` and no key, eisy-ai shows a
notice that it's running in MCP-only mode; with `mcp_server` off and no key, it shows a notice that
a key is needed. Either way, adding a key and restarting clears the notice.

---

## Switching between modes

There are two ways to switch, and they behave differently.

**Just ask.** Tell eisy-ai what you want — "I'd like to build a plugin for my SimpliSafe alarm,"
or, from inside developer mode, "turn off the living room lights" — and it switches on your
behalf, automatically, mid-conversation. You never have to ask for the switch explicitly. There's
a limit of one automatic switch per message by default, so if a single message would require
bouncing back and forth more than that, eisy-ai will say so rather than attempting it — just
split the request across a couple of messages instead.

**Type the command directly.** Send a message containing *only* `/developer` or `/customer` (no
other text in that message) to switch immediately and deterministically, no interpretation
involved. The switch is **sticky** — it stays in effect for the rest of the conversation until
you switch again, either command or just by asking. You'll get a plain confirmation
("Switched to developer tools." / "Switched to customer tools.") in response.

One important consequence either way: **the two modes don't share conversation history.**
Developer mode can't see anything said while you were in customer mode, and vice versa. When a
switch happens because you asked for something (not via the explicit command), eisy-ai carries
over a short summary of what you want so you don't have to repeat yourself — but anything beyond
that summary is gone once you're on the other side. If you switch with the explicit `/developer`/
`/customer` command instead, no summary carries over at all — just say what you need once you're
there.

If a mode isn't enabled on your installation, switching to it will fail with a plain explanation
rather than silently doing nothing.

---

## Managing saved sessions

As long as you're signed in, each mode (customer and developer) keeps its own conversation
history — and, separately, can hold more than one *named* session, the way browser tabs or
documents do. Your current session keeps growing as you talk, survives reconnecting, and (on
installations with persistent session storage turned on) survives a full restart of eisy-ai
itself. Five commands manage it, each sent as a message containing *only* the command (plus an id
and/or name where one is needed):

| Command | What it does |
|---|---|
| `/sessions` | Lists your saved sessions in the current mode as a table (id, name, description), marking which one is current. |
| `/new-session` | Starts a fresh, empty session in the current mode. Your previous one isn't lost — it's just no longer the one you're talking in. |
| `/load-session <id>` | Switches to a saved session by its id (see `/sessions`), replaying its history so you can pick back up where you left off. |
| `/rename-session <id> <name>` | Gives a saved session a more memorable name than "Session 3". |
| `/delete-session <id>` | Removes a saved session. Deleting your current session automatically starts a new empty one in its place — you always have at least one. |

Customer and developer mode sessions are entirely separate: `/sessions` only shows (and
`/new-session`/`/load-session`/etc. only act on) the mode you're currently in.

If a session command replies that session management "isn't enabled on this installation," your
eisy administrator hasn't turned on persistent session storage — talk to them if you'd like this
feature.

---

## 1. For Customers

Everything below is available through ordinary conversation — you describe what you want, and
eisy-ai figures out which of its capabilities to use. A few behaviors apply everywhere and are
worth knowing up front:

> **Deletions require a literal "YES."** Deleting a device, scene, folder, routine, variable, or
> installed plugin never happens on the first ask. eisy-ai previews what would be removed, and
> only goes through if your very next reply is exactly the word `YES` — "yes," "sure," and "go
> ahead" don't count. This is deliberate: it's your one safety net against an accidental delete.
>
> Several other actions — removing a single device from a scene, running a live scene test,
> restarting a service, buying or installing a plugin, changing a plugin's settings — also wait
> for your explicit go-ahead, just without the strict `YES` requirement.

### Checking on and controlling devices

- **"Is the porch light on?" / "What's the temperature in the den?"** — eisy-ai can check the
  current state of one or more devices in a single question.
- **"Turn off the kitchen lights." / "Set the thermostat to 68."** — control one or many devices
  at once: on/off, dimming, mode changes, setting values, or anything else a device supports.
- **"What can the thermostat actually do?"** — look up everything a specific device or scene
  supports, including valid ranges and choices for each setting.
- **"Why did the garage light turn on last night?" / "How often does the back door open?"** —
  eisy-ai keeps a standing activity log it can check any time, not just when something's broken.
  It answers simple "what happened" questions as well as aggregate ones (counts, trends,
  patterns), and if it genuinely can't find an automated cause, it'll say so plainly rather than
  guess — most likely someone just did it by hand.

### Organizing your devices

- **Rename, enable/disable, move, or delete** a device, scene, or folder.
- **Folders** are purely organizational — no automation behavior of their own — for when you just
  want to tidy up your device list.
- Deleting works directly for Insteon devices. **Z-Wave, Zigbee, and Matter devices are removed
  through the pairing flow's "exclude" step instead** (see Adding & Removing Devices, below), and
  a device created by a plugin is removed by uninstalling that plugin.

### Scenes & groups

- **Create a scene** and decide which device is the "controller" (the trigger) and which are
  "responders" (what reacts) — this is also how two devices get directly cross-linked to each
  other.
  - A device can only control one scene at a time. If you try to add an already-controlling
    device to a new scene, eisy-ai will tell you which scene it's already tied to and ask how
    you'd like to proceed, rather than silently overriding it.
- **Remove a member from a scene**, or change how an existing member behaves when the scene
  activates (dimmer level, fade speed, etc.).
- **"What happens when I run my 'Movie Night' scene?"** — get a plain explanation of exactly
  which devices respond and how.
- **"Why doesn't my scene turn everything off?"** — run a real test: eisy-ai fires an actual "off"
  command to the group and reports which members responded (only after you agree, since it
  genuinely switches things off; currently Insteon scenes only).

### Variables

Small counters or on/off-style flags your routines can use as conditions or results.

- List every saved variable and its current value.
- Create, update, or delete one (deletion follows the standard two-step confirmation).

### Routines & automations

- **Build a new automation, or change an existing one** — pairing conditions (a device's status,
  a button press, a schedule, sunrise/sunset, another routine's state, a variable, a utility
  signal) with actions (control devices, wait, repeat, adjust a scene, send a notification,
  change a variable, control another routine). One thing worth knowing: editing an existing
  routine rewrites its whole logic rather than patching one piece, so describe the complete
  behavior you want — eisy-ai reviews the current version first so nothing you didn't ask to
  change gets dropped.
- **"What does my 'Away Mode' routine actually do?"** — get a plain-language explanation plus its
  live status (enabled/disabled, currently running, last/next run time).
- **Turn a routine on/off, run it immediately, stop it, toggle whether it runs at startup, or
  delete it.**

### Plugins — extending what eisy-ai can do

Plugins add new device types, specialized computed answers, or extra features eisy-ai doesn't
have built in. They exist in three states, each with its own listing:

- **Browse the store**, **see what you've already purchased**, and **see what's actually
  installed and running**.
- **Buy** or **install** a plugin — in both cases, eisy-ai hands you a link, and you finish the
  purchase or installation yourself on the web; neither completes inside the chat.
- **Uninstall** an installed plugin — this one *does* happen directly through the assistant,
  permanently, with the standard two-step confirmation.
- **Start, stop, or restart** a plugin's own background service (separate from restarting the
  whole eisy).
- **Use a plugin's own special features** — eisy-ai can discover what an AI-capable plugin
  specifically offers and actually use it to answer your question or help build a scene/routine.
- **View or change a plugin's settings** — API keys, polling frequency, device-specific options,
  connected-account credentials — only after you've agreed to the specific change. This only
  applies to plugin-provided features, never to a regular Insteon/Z-Wave/Zigbee/Matter device.

### Adding & removing physical devices (pairing)

- **Adding a device**: eisy-ai first asks whether you have a QR code or setup code. If you do, it
  scans/enters it directly. If not, it falls back to a protocol-specific flow — Insteon by address
  or by opening a "linking mode" window (up to 5 minutes, enough for several devices back to
  back); Z-Wave/Zigbee by opening discovery mode; Matter strictly requires a QR/setup code. X10
  isn't supported through chat — you'll be walked through pairing it manually instead. Either
  way, this involves a real physical step (scanning a code, pressing a button) while eisy-ai
  waits.
- **Removing a device**: for Z-Wave, you identify the device physically (its own exclude button)
  rather than naming it in chat; Zigbee and Matter remove immediately on request, no physical
  step needed (Zigbee removal can occasionally need a manual fix in the web UI if it fails).

### Diagnostics & troubleshooting

Reach for these when something's actually broken — everyday "what's the temperature" questions
are answered by ordinary device status checks, not these tools.

- **"I turn it on but nothing happens"** — investigates commands from eisy-ai not reaching the
  device.
- **"I flipped the switch by hand and eisy-ai never noticed"** — investigates the device's status
  not making it back.
- **System health** — which wireless subsystems (Insteon/Z-Wave/Zigbee/Matter) are enabled and
  connected, firmware/software versions, and whether updates are available.
- **Core services** — check whether the eisy's internal services are running, and start/stop/
  restart one (only after you agree, since it briefly interrupts it).
- **"What protocol does this device use?"** — useful context behind the scenes for any
  protocol-specific question or action.
- **Run a command on the host computer** — a broad, advanced escape hatch for technical requests
  nothing else covers. This is a genuinely powerful, unrestricted capability, distinct from
  everyday smart-home control — eisy-ai will explain what a command does before running anything
  that changes or restarts something.

### Preferences

- **Aliases** — "when I say 'the lamp,' I mean the one in the office" — nicknames for devices or
  scenes.
- **Reminders** — birthdays, anniversaries, or other dated events, repeating annually or one-time,
  optionally flagged some number of days in advance. There's no "edit" today — changing one means
  deleting and re-creating it. Also worth knowing: a saved reminder doesn't send a notification
  anywhere yet — it simply shows as "coming up soon" the next time your preferences are checked.

### Time & location

Exact current time (with time zone), today's sunrise/sunset, and your installation's time zone —
useful for "what time is it," "is it dark yet," or "in the last 20 minutes" style questions.

### Developer mode

Building your own plugin is a separate, advanced mode — not something you'll need for everyday
use. See "Switching between modes" above for how to get there, and "For Developers" below for
what it can do.

---

## 2. For Developers

Developer mode walks you through building a real, working eisy/IoX plugin end to end,
conversationally: researching the target device or service, defining how it shows up as a node,
generating the actual plugin code, testing it on a real eisy, debugging it in VS Code, and pushing
it to GitHub. Not sure how you got here? See "Switching between modes" above — the same
`/customer` command (or just asking) takes you back. A few rules apply across the whole workflow:

> **Generating a plugin only ever touches your local disk.** Nothing changes on a real eisy until
> you explicitly install it. Installing, updating a registration, and deleting a registered or
> installed plugin all require your explicit go-ahead first.
>
> **Secrets never get written into generated code.** Any real secret value found in a search
> query, a fetched page, or generated source causes generation to refuse outright. An OAuth
> `client_id`/`client_secret` is always a placeholder at generation time — the real values get
> set afterward, once the plugin is installed.
>
> **Two destructive actions share one strict confirm pattern.** Deleting a plugin's registration
> or an installed plugin both preview first, then require a second call *and* your very next
> reply being the literal word `YES` before anything is actually removed.

### Getting started

Before anything gets generated, eisy-ai commissions a one-time developer identity for your whole
workspace — your email, display name, and optional GitHub URL, stamped into every plugin you
generate under it. It checks whether one's already on file before ever asking you to set one, and
won't overwrite an existing identity without you asking to change it.

### Researching a device or API

Before building anything, eisy-ai gathers real evidence about the device/service you're
targeting — this is a hard prerequisite; generation refuses without it.

- **Check the store first.** It always checks whether a plugin covering your need already exists,
  and recommends stopping there unless you specifically want a custom build anyway.
- **Search GitHub** for an existing eisy/IoX plugin or a device's own API client to use as
  reference — any repo whose license isn't MIT/Apache-2.0/BSD gets flagged reference-only, never
  to be copied from.
- **Search the web** for a device's official API docs (when a search backend is configured).
- **Fetch a specific page** you or search found, treated strictly as reference data, never as
  instructions.

Every source gets accumulated across sessions into your plugin's own history, and license status
travels with it into the generated `LICENSE.md`.

### Defining the device (the Dynamic Profile)

Before a plugin is generated, you define how the device shows up to eisy/IoX — its properties,
commands, and UI editors (this is the "Dynamic Profile": nodedefs/editors/linkdefs).

- **Look up the right standard property id** (e.g. `ST`, `CLITEMP`, `CLIHUM`) instead of
  inventing one — or invent a short, well-formed one if nothing standard fits.
- **Look up the right unit-of-measure id** for a property's valid range, rather than guessing —
  one property can even offer more than one unit (e.g. a temperature in both °F and °C).
- **Validate the whole profile** before generating anything — catches missing ids, dangling
  references, malformed commands, and several other hard-enforced rules (every non-Controller
  node needs its own real "status" property; no nodedef may declare the same property twice).

A unit or a named value is never "locked in" at generation time — a profile can even be updated
live, after the plugin is already running (e.g. to reflect names the customer entered later).

### Generating the plugin

This is the core step: one call produces a complete, working plugin directory — the actual
Python code (wiring always tool-generated; you only supply the behavior that's specific to your
device), its registration file, requirements, an install script, README/LICENSE, a starter test
suite, and a running history of what's changed across sessions.

- If files already exist, the first call just shows you what would conflict and writes nothing —
  you decide whether to overwrite.
- Already have a plugin in progress? eisy-ai can list everything you've generated so far and load
  one back into the conversation to keep iterating, rather than starting from scratch.
- A smaller, faster "just refresh the generated wiring" option exists too, for picking up a
  template fix without re-supplying your whole original plugin spec.

### Advanced plugin features

All configured as part of generating your plugin:

- **OAuth** — for a device/service that requires it, eisy-ai wires up the full token lifecycle
  (your plugin's code never needs to hand-check whether it's authenticated yet); you set the real
  client id/secret only after install.
- **Webhooks** — for a plugin that needs to *receive* pushed calls from a third-party service
  (not just call out to one). Requires your eisy to already have remote access configured — eisy-ai
  can't verify or turn that on for you.
- **AI tools** — your plugin can declare its own callable capabilities, which show up to
  customers the same way any other plugin's features do.
- **Typed configuration fields** — beyond simple text fields, a plugin's settings page can offer
  real number/boolean types, required fields, repeatable lists, and grouped fields, when the
  config genuinely needs that structure.

### Local dev environment & VS Code

- **An isolated Python environment** gets set up for your plugin automatically before it's ever
  installed on a real eisy, keeping its dependencies separate from anything else on your machine.
- **One-click VS Code debugging** — once your plugin is installed, eisy-ai wires up a debug
  configuration using the exact same credentials the live service uses, so you can attach a
  debugger directly to it. Safe to redo after every restart.

### Git & GitHub

- **One-time repo setup** — initializes git, writes a `.gitignore` that guarantees your local
  secrets file never gets committed, makes the first commit, and pushes to a GitHub repo you've
  already created. Only happens with your explicit go-ahead, and is safe to call again later
  (it skips anything already done).
- **Everyday git work** — status, diffs, log, stashing, pulling, ad hoc commits — just happens
  through an ordinary shell command in your plugin's directory; no special tool needed.

### Installing & testing on a real eisy

- **Install** — registers, installs, and starts your plugin on a real eisy, reporting each stage
  separately so a partial failure is never mistaken for a full success. Always requires your
  go-ahead, since it makes real changes.
- If the eisy already knows about this plugin, eisy-ai won't silently re-register or reinstall over
  it — you choose between **updating the existing registration in place** or **deleting it and
  starting fresh**.

### Working with an installed plugin

Once installed, you get the exact same tools a customer-facing conversation would use, so you can
run through the whole real-world loop yourself:

- See what's installed and its current state.
- Read and write its configuration — always read first, then send back the same shape, modified.
- Start, stop, or restart its service.
- Discover and actually call its own declared AI features.
- Uninstall it (permanent, with the standard double confirmation).
- Run shell commands for anything else — inspecting logs, running your test suite inside the
  plugin's own environment, and so on.

### Hardware & USB devices

For a plugin that needs direct access to a USB or serial device: eisy-ai walks you through taking
a "before" snapshot of connected devices, asking you to plug yours in, taking an "after" snapshot,
and automatically identifying the new device from the difference.
