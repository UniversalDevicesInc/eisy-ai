# eisy-ai

eisy-ai is your AI companion for eisy. It can help with complex tasks such as:

- Creating sophisticated routines based on your devices, preferences, and plugins
- Running complex diagnostics using your system configuration and logs
- Investigating why something turned on or off seemingly randomly
- Supporting plans such as planning a new installation or a vacation

You will be using your own LLM/model and API Keys. 


# Configuration Parameters

1. Provider
** Mandatory **
This is the name of your frontier LLM provider. Currently limited to:
| Anthropic Claude | `anthropic`
| OpenAI | `openai` 
| xAI Grok | `grok`

Support for local LLM is in the works.

2. API Key
** Mandatory **
The API Key for the provider being used

3. Model
** Optional **
If not provided, based on the provider, we'll default to the least expensive model that's been tested and works with the current use cases.
* Examples:
`claude-haiku-4-5-20251001`
`gpt-5.6-luna`
`grok-4-fast`
