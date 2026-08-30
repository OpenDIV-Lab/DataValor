"""Optional DataEval backends.

Backends are deliberately not imported here: importing :mod:`datavalor.data_eval`
must remain safe when optional dependencies are absent.  Import a class from its
concrete module when it is selected in a pipeline.
"""

__all__: list[str] = []
