"""Process-wide foundations every package imports: nothing here is an op.

| module | holds |
|---|---|
| `_bootstrap.py` | import-time side effects — load the env file, install the ResourceHub, wrap LLM calls with a deadline |
| `config.py` | every setting — stage routing from `models.yaml`, toggles from env |
| `conversation.py` | `Conversation` and the ASR fixes applied to it |
| `prompts.py` | `PROMPTS` — every `.prompt` file, keyed by stem |
"""
