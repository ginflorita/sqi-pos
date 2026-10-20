"""Local bazaar point of sale."""
import sys
from pathlib import Path

vendor=Path(__file__).resolve().parent.parent/'.vendor'
if vendor.exists():
    sys.path.insert(0,str(vendor))
