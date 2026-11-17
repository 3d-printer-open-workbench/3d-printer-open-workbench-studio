"""Moved to ``workbench_core.fontinfo`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.fontinfo as _impl

sys.modules[__name__] = _impl
