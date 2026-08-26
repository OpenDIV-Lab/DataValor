import importlib

from datavalor import MODULES, __version__


def test_public_modules_are_ordered_and_importable():
    assert [module.order for module in MODULES] == list(range(7))
    assert len({module.display_name for module in MODULES}) == len(MODULES)
    for module in MODULES:
        assert importlib.import_module(module.import_path) is not None


def test_package_is_explicitly_pre_alpha():
    assert __version__.endswith("a0")

