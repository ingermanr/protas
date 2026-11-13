"""Helpers shared by the tests."""

from unittest import mock

from protas import db


def at_version_3():
    """Make protas behave as the release whose schema was version 3.

    Used to build a database as an installed protas left it, before the
    code under test opens it.
    """
    return mock.patch.multiple(
        "protas.db", SCHEMA=db.SCHEMA_V3, MIGRATIONS={}, SCHEMA_VERSION=3
    )


def pin_version_3(case):
    """Run a whole test as the protas whose schema was version 3.

    The tests of the update chain register steps of their own on top of
    version 3; pinning keeps them about the chain and not about whatever
    the newest schema happens to be.
    """
    patcher = at_version_3()
    patcher.start()
    case.addCleanup(patcher.stop)


def at_version_4():
    """Make protas behave as the release whose schema was version 4."""
    return mock.patch.multiple(
        "protas.db",
        SCHEMA=db.SCHEMA_V4,
        MIGRATIONS={3: db._add_recurrences},
        SCHEMA_VERSION=4,
    )


def pin_version_4(case):
    """Run a whole test as the protas whose schema was version 4."""
    patcher = at_version_4()
    patcher.start()
    case.addCleanup(patcher.stop)
