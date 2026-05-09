"""Cross-platform helper tools for mumble-docker.

Each subcommand lives in its own module and exposes a ``main(argv)``
function returning an exit code.  Run them via the dispatcher::

    python -m tools <command> [options]

or directly::

    python -m tools.dev_build [options]
"""
