"""Monitoring collectors.

Collectors are synchronous by design and are called from the agent's event
loop via asyncio.to_thread - psutil calls must never run inline.
"""
