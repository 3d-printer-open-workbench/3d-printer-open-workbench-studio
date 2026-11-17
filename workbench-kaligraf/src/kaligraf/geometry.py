"""Moved to ``workbench_core.geometry`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.geometry as _impl

sys.modules[__name__] = _impl
