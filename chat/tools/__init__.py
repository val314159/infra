from . import shell

__index__ = {
    k: v
    for n, m in  globals().items() if not n.startswith("_")
    for k, v in m.__dict__.items() if not k.startswith("_") and callable(v)
}

__all__ = [ shell ]

