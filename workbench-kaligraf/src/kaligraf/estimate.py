"""Moved to ``workbench_core.estimate`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.estimate as _impl

sys.modules[__name__] = _impl
