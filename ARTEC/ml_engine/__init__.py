"""Moteur ML ARTEC : validation, indicateurs, anomalies et scores de qualité perçue.

Interface stable pour Django :
    from ml_engine import analyze_batch
"""
from .prediction import analyze_batch
from .schemas import ENGINE_VERSION, EngineConfig

__all__ = ["analyze_batch", "EngineConfig", "ENGINE_VERSION"]
__version__ = ENGINE_VERSION
