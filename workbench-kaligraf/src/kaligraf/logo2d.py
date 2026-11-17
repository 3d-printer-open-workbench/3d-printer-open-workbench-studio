"""Moved to ``workbench_core.logo2d`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.logo2d as _impl

sys.modules[__name__] = _impl
