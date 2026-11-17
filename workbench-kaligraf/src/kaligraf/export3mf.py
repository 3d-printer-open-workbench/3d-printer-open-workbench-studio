"""Moved to ``workbench_core.export3mf`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.export3mf as _impl

sys.modules[__name__] = _impl
