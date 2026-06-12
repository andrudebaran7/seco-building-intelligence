import sys
from pathlib import Path

# Los módulos del proyecto viven en la raíz del repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
