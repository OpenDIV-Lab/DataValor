"""Command-line entry points for DataValor workflows."""


def main(argv=None):
    """Lazy wrapper so ``python -m datavalor.cli.main`` has no import warning."""
    from .main import main as _main

    return _main(argv)


__all__ = ["main"]
