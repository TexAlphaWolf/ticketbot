"""Column types: text that is encrypted in the database and plain in Python."""

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from ..core import crypto


class EncryptedText(TypeDecorator):
    """Text encrypted with the active keyring; `context` is the column (table.column)."""

    impl = Text
    cache_ok = True

    def __init__(self, context: str):
        super().__init__()
        self.context = context

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return crypto.active().encrypt(value, self.context)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return crypto.active().decrypt(value, self.context)
