"""
SkyMaster Drone Platform - Path Planning API Endpoints
RESTful API for path planning operations
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

# Import planning modules
import sys
sys.path.insert(0, '/home/dudu/.nanobot/workspace/skymaster-drone-platform/backend')

from core.planning import AStarPlanner, PathPlanner, TerrainProcessor
from core.planning.astar import Obstacle, ObstacleType, Position
from core.planning.path_planner import (
    DroneConstraints,
    PlanningStrategy,
    PlanningResult
)
from core.planning.terrain import TerrainGrid

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/planning", tags=["Path Planning"])

# Initialize planning components
terrain_processor = TerrainProcessor()
astar_planner = AStarPlanner()
path_planner = PathPlanner(
    terrain_processor=terrain_processor,
    astar_planner=astar_planner
)


# ============================================================================
# Request/Response Models
# ============================================================================

class PositionModel(BaseModel):
    """3D position model"""
    x: float = Field(..., description="X coordinate (meters)")
    y: float = Field(..., description="Y coordinate (meters)")
    z: float = Field(0.0, description="Z coordinate / altitude (meters)")
    
    @validator('z')
    def validate_altitude(cls, v):
        if v < 0 or v > 500:
            raise ValueError('Altitude must be between 0 and 500 meters')
        return v


class ObstacleModel(BaseModel):
    """Obstacle definition model"""
    position: PositionModel
    radius: float = Field(..., gt=0, description="Obstacle radius (meters)")
    height: float = Field(..., gt=0, description="Obstacle height (meters)")
    obstacle_type: str = Field("static", description="Type of obstacle")
    safety_margin: float = Field(5.0, ge=0, description="Safety margin (meters)")


class PathRequest(BaseModel):
    """Path planning request"""
    start: PositionModel
    goal: PositionModel
    strategy: str = Field(
        "shortest",
        description="Planning strategy: shortest, energy_efficient, terrain_following, safety_first"
    )
    obstacles: Optional[List[ObstacleModel]] = Field(
        default=[],
        description="List of obstacles to avoid"
    )
    terrain_bounds: Optional[Dict[str, float]] = Field(
        default=None,
        description="Terrain bounds: {min_lat, min_lon, max_lat, max_lon}"
    )
    
    @validator('strategy')
    def validate_strategy(cls, v):
        valid_strategies = [
            'shortest', 'energy_efficient', 
            'terrain_following', 'safety_first'
        ]
        if v not in valid_strategies:
            raise ValueError(f'Strategy must be one of: {valid_strategies}')
        return v


class OptimizeRequest(BaseModel):
    """Path optimization request"""
    path: List[PositionModel]
    optimization_type: str = Field(
        "energy",
        description="Optimization type: energy, terrain, smooth"
    )
    terrain_bounds: Optional[Dict[str, float]] = None


class TerrainRequest(BaseModel):
    """Terrain data request"""
    bounds: Dict[str, float] = Field(
        ...,
        description="Geographic bounds: {min_lat, min_lon, max_lat, max_lon}"
    )
    resolution: Optional[float] = Field(10.0, description="Grid resolution (meters)")


class MultiGoalRequest(BaseModel):
    """Multi-goal path planning request"""
    start: PositionModel
    goals: List[PositionModel] = Field(..., min_items=1)
    strategy: str = Field("shortest", description="Planning strategy")


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/path", response_class=JSONResponse)
async def generate_path(
    request: PathRequest,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Generate a path from start to goal
    
    Supports multiple planning strategies:
    - shortest: Minimize total distance
    - energy_efficient: Minimize energy consumption
    - terrain_following: Follow terrain contours
    - safety_first: Maximize safety margins
    """
    logger.info(
        f"Path planning request: {request.start.dict()} -> {request.goal.dict()} "
        f"using {request.strategy} strategy"
    )
    
    try:
        # Convert models to internal types
        start = Position(**request.start.dict())
        goal = Position(**request.goal.dict())
        
        # Map strategy
        strategy_map = {
            'shortest': PlanningStrategy.SHORTEST,
            'energy_efficient': PlanningStrategy.ENERGY_EFFICIENT,
            'terrain_following': PlanningStrategy.TERRAIN_FOLLOWING,
            'safety_first': PlanningStrategy.SAFETY_FIRST
        }
        strategy = strategy_map.get(request.strategy, PlanningStrategy.SHORTEST)
        
        # Convert obstacles
        obstacles = []
        if request.obstacles:
            for obs in request.obstacles:
                obstacles.append(Obstacle(
                    position=Position(**obs.position.dict()),
                    radius=obs.radius,
                    height=obs.height,
                    obstacle_type=ObstacleType(obs.obstacle_type),
                    safety_margin=obs.safety_margin
                ))
        
        # Get terrain if bounds provided
        terrain = None
        if request.terrain_bounds:
            bounds = (
                request.terrain_bounds['min_lat'],
                request.terrain_bounds['min_lon'],
                request.terrain_bounds['max_lat'],
                request.terrain_bounds['max_lon']
            )
            terrain = await terrain_processor.get_elevation_data(bounds)
        
        # Plan path
        result = await path_planner.plan_path(
            start=start,
            goal=goal,
            strategy=strategy,
            obstacles=obstacles,
            terrain=terrain
        )
        
        if result.success:
            return {
                "success": True,
                "message": result.message,
                "path": result.path.to_dict() if result.path else None,
                "statistics": path_planner.get_path_statistics(result.path) if result.path else None
            }
        else:
            return {
                "success": False,
                "message": result.message,
                "path": None
            }
            
    except Exception as e:
        logger.error(f"Path planning error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Planning failed: {str(e)}")


@router.post("/optimize", response_class=JSONResponse)
async def optimize_path(request: OptimizeRequest) -> Dict[str, Any]:
    """
    Optimize an existing path
    
    Optimization types:
    - energy: Reduce energy consumption
    - terrain: Adjust for terrain following
    - smooth: Smooth the path
    """
    logger.info(
        f"Path optimization request: {len(request.path)} waypoints, "
        f"type: {request.optimization_type}"
    )
    
    try:
        # Convert path
        path = [Position(**p.dict()) for p in request.path]
        
        if len(path) < 2:
            raise HTTPException(
                status_code=400,
                detail="Path must have at least 2 waypoints"
            )
        
        # Get terrain if needed
        terrain = None
        if request.optimization_type == "terrain" and request.terrain_bounds:
            bounds = (
                request.terrain_bounds['min_lat'],
                request.terrain_bounds['min_lon'],
                request.terrain_bounds['max_lat'],
                request.terrain_bounds['max_lon']
            )
            terrain = await terrain_processor.get_elevation_data(bounds)
        
        # Apply optimization
        if request.optimization_type == "energy":
            optimized = await path_planner.optimize_energy(path, terrain)
        elif request.optimization_type == "terrain":
            if not terrain:
                raise HTTPException(
                    status_code=400,
                    detail="Terrain bounds required for terrain optimization"
                )
            optimized = await path_planner.terrain_following(path, terrain)
        elif request.optimization_type == "smooth":
            optimized = astar_planner.smooth_path(path)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown optimization type: {request.optimization_type}"
            )
        
        # Calculate metrics
        original_length = astar_planner.calculate_path_length(path)
        optimized_length = astar_planner.calculate_path_length(optimized)
        
        return {
            "success": True,
            "message": f"Path optimized using {request.optimization_type}",
            "original_waypoints": len(path),
            "optimized_waypoints": len(optimized),
            "original_length": original_length,
            "optimized_length": optimized_length,
            "length_change": optimized_length - original_length,
            "optimized_path": [p.to_tuple() for p in optimized]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Optimization error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Optimization failed: {str(e)}")


@router.post("/terrain", response_class=JSONResponse)
async def get_terrain(request: TerrainRequest) -> Dict[str, Any]:
    """
    Get terrain elevation data for a geographic region
    
    Returns terrain grid with:
    - Elevation data
    - Slope information
    - Terrain classification
    - Difficulty metrics
    """
    logger.info(f"Terrain request for bounds: {request.bounds}")
    
    try:
        # Validate bounds
        required_keys = ['min_lat', 'min_lon', 'max_lat', 'max_lon']
        if not all(key in request.bounds for key in required_keys):
            raise HTTPException(
                status_code=400,
                detail=f"Bounds must include: {required_keys}"
            )
        
        bounds = (
            request.bounds['min_lat'],
            request.bounds['min_lon'],
            request.bounds['max_lat'],
            request.bounds['max_lon']
        )
        
        # Set resolution if provided
        if request.resolution:
            terrain_processor.grid_resolution = request.resolution
        
        # Get terrain data
        terrain = await terrain_processor.get_elevation_data(bounds)
        
        # Analyze terrain
        difficulty = terrain_processor.analyze_terrain_difficulty(terrain)
        
        # Sample terrain profile (simplified for API response)
        sample_size = min(100, terrain.shape[0] * terrain.shape[1])
        step_x = max(1, terrain.shape[0] // 10)
        step_y = max(1, terrain.shape[1] // 10)
        
        elevation_samples = []
        for x in range(0, terrain.shape[0], step_x):
            for y in range(0, terrain.shape[1], step_y):
                elevation_samples.append({
                    'x': x,
                    'y': y,
                    'elevation': terrain.get_elevation(x, y),
                    'slope': terrain.get_slope(x, y)
                })
        
        return {
            "success": True,
            "message": "Terrain data retrieved successfully",
            "grid_info": {
                "width": terrain.shape[0],
                "height": terrain.shape[1],
                "resolution": terrain.resolution,
                "origin": {
                    "latitude": terrain.origin_lat,
                    "longitude": terrain.origin_lon
                }
            },
            "elevation_range": {
                "min": float(terrain.elevations.min()),
                "max": float(terrain.elevations.max()),
                "mean": float(terrain.elevations.mean())
            },
            "difficulty": difficulty,
            "samples": elevation_samples[:sample_size]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Terrain retrieval error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Terrain retrieval failed: {str(e)}")


@router.post("/multi-goal", response_class=JSONResponse)
async def plan_multi_goal(request: MultiGoalRequest) -> Dict[str, Any]:
    """
    Plan a path visiting multiple goals
    
    Uses nearest-neighbor heuristic for goal ordering
    """
    logger.info(f"Multi-goal planning: {len(request.goals)} goals")
    
    try:
        start = Position(**request.start.dict())
        goals = [Position(**g.dict()) for g in request.goals]
        
        # Map strategy
        strategy_map = {
            'shortest': PlanningStrategy.SHORTEST,
            'energy_efficient': PlanningStrategy.ENERGY_EFFICIENT,
            'terrain_following': PlanningStrategy.TERRAIN_FOLLOWING,
            'safety_first': PlanningStrategy.SAFETY_FIRST
        }
        strategy = strategy_map.get(request.strategy, PlanningStrategy.SHORTEST)
        
        # Plan multi-goal path
        result = await path_planner.multi_goal_planning(
            start=start,
            goals=goals,
            strategy=strategy
        )
        
        if result.success:
            return {
                "success": True,
                "message": result.message,
                "path": result.path.to_dict() if result.path else None,
                "statistics": path_planner.get_path_statistics(result.path) if result.path else None
            }
        else:
            return {
                "success": False,
                "message": result.message,
                "path": None
            }
            
    except Exception as e:
        logger.error(f"Multi-goal planning error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Planning failed: {str(e)}")


@router.get("/health", response_class=JSONResponse)
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for path planning service
    """
    return {
        "status": "healthy",
        "service": "path_planning",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "terrain_processor": "operational",
            "astar_planner": "operational",
            "path_planner": "operational"
        }
    }


@router.get("/strategies", response_class=JSONResponse)
async def list_strategies() -> Dict[str, Any]:
    """
    List available planning strategies
    """
    return {
        "strategies": [
            {
                "id": "shortest",
                "name": "Shortest Path",
                "description": "Minimize total path distance using A* algorithm"
            },
            {
                "id": "energy_efficient",
                "name": "Energy Efficient",
                "description": "Minimize energy consumption by optimizing altitude changes"
            },
            {
                "id": "terrain_following",
                "name": "Terrain Following",
                "description": "Follow terrain contours with safe clearance"
            },
            {
                "id": "safety_first",
                "name": "Safety First",
                "description": "Maximize safety margins and avoid risky areas"
            }
        ]
    }


# ============================================================================
# Utility Functions
# ============================================================================

def setup_planning_routes(app):
    """Setup planning routes on the main FastAPI app"""
    app.include_router(router)
    logger.info("Path planning routes registered")


# For standalone testing
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI
    
    app = FastAPI(title="SkyMaster Path Planning API")
    setup_planning_routes(app)
    
    uvicorn.run(app, host="0.0.0.0", port=8001)
