"""Shared pytest lifecycle hooks."""

import logging


def pytest_sessionfinish(session, exitstatus) -> None:
    del session, exitstatus
    # Airflow replaces pytest's logging handler; silence Py4J after Spark has stopped so its
    # interpreter-shutdown destructor cannot write to pytest's already closed capture stream.
    logging.getLogger("py4j").disabled = True
    logging.getLogger("py4j.clientserver").disabled = True
