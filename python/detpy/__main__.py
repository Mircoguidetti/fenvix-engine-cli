from . import _support

if _support.PROBLEM is not None:
    _support.refuse()

from .cli import main  # noqa: E402

raise SystemExit(main())
