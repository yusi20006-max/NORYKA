# Bale platform plugin for Noryka
from .adapter import BaleAdapter, BalePlatform

def get_adapter(*args, **kwargs):
    return BaleAdapter(*args, **kwargs)

__all__ = ["BaleAdapter", "BalePlatform", "get_adapter"]
