"""Service package.

Keep this module side-effect free so importing sibling modules like
`app.services.learning_profile` does not eagerly import `database.py`
before `.env` files have been loaded by `app.server`.
"""

__all__ = []
