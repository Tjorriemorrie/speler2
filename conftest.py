import pytest
from pytest_django.plugin import blocking_manager_key


@pytest.hookimpl(hookwrapper=True)
def pytest_collection(session: pytest.Session):
    """Let the module level queries in `main.plays` run while test modules are imported.

    `main.plays` sizes its rotation constants off the library at import time, and
    pytest-django blocks database access outside of the `db` fixture - which would
    otherwise turn importing `main/tests.py` into a collection error.
    """
    with session.config.stash[blocking_manager_key].unblock():
        yield
