"""Moved to ``workbench_core.template_pdf`` (S1). This name stays an alias of the same module object."""
import sys

import workbench_core.template_pdf as _impl

sys.modules[__name__] = _impl
