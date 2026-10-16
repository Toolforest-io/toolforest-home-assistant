"""Load pure bridge/executor modules without bootstrapping HA at import time."""

import sys
import types
from pathlib import Path

package = types.ModuleType("ha_toolforest")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "toolforest")]
sys.modules["ha_toolforest"] = package
