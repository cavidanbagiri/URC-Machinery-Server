from argon2 import PasswordHasher
import asyncio

class PasswordHash:

    __slots__ = 'ph'

    def __init__(self):
        self.ph = PasswordHasher()

    def hash_password(self, plain_password: str):
        h_password = self.ph.hash(plain_password)
        return h_password

    async def verify(self, h_password: str, plain_password: str):
        """Async wrapper for password verification"""
        try:
            # Run sync verify in thread pool to avoid blocking
            return await asyncio.to_thread(self.ph.verify, h_password, plain_password)
        except Exception as ex:
            return False