"""Allow running CLI as: python -m robo_cortex.cli"""

import sys
from robo_cortex.cli import main

sys.exit(main())
