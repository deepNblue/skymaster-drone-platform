"""
SkyMaster Drone Platform - API v1 Module
"""

from .planning import router as planning_router
from .safety import router as safety_router

__all__ = ['planning_router', 'safety_router']
