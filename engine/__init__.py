"""Engine - central coordination hub.

Linux only: asyncio here is backed by epoll. Owns all persistence; the
client and admin components have no database of their own.
"""
