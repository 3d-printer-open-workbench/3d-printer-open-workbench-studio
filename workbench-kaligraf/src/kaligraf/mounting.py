"""Moved to ``workbench_core.mounting`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.mounting as _impl

sys.modules[__name__] = _impl
