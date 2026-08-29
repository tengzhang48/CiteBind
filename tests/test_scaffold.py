"""T-01 scaffold: the package must be importable and carry a version."""

import citebind


def test_version_is_nonempty_string():
    assert isinstance(citebind.__version__, str)
    assert citebind.__version__
