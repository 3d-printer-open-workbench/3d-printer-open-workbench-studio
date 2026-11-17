"""Moved to ``workbench_core.render`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.render as _impl

sys.modules[__name__] = _impl
