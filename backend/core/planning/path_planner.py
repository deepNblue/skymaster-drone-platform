"""
SkyMaster Drone Platform - Path Planning System
Main path planning orchestrator with multiple planning strategies
"""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .astar import AStarPlanner, Obstacle, Position
from .terrain import TerrainGrid, TerrainProcessor

logger = logging.getLogger(__name__)


class PlanningStrategy(Enum):
    """Path planning strategies"""
    SHORTEST = "shortest"
    ENERGY_EFFICIENT = "energy_efficient"
    TERRAIN_FOLLOWING = "terrain_following"
    SAFETY_FIRST = "safety_first"
    TIME_OPTIMAL = "time_optimal"


class PathStatus(Enum):
    """Path execution status"""
    PLANNED = "planned"
    VALIDATING = "validating"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ABORTED = "aborted"


@dataclass
class Waypoint:
    """Path waypoint with metadata"""
    position: Position
    speed: float = 10.0  # m/s
    heading: Optional[float] = None  # degrees
    hold_time: float = 0.0  # seconds
    is_checkpoint: bool = False
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'position': self.position.to_tuple(),
            'speed': self.speed,
            'heading': self.heading,
            'hold_time': self.hold_time,
            'is_checkpoint': self.is_checkpoint
        }


@dataclass
class PlannedPath:
    """Complete planned path with metadata"""
    id: str
    waypoints: List[Waypoint]
    strategy: PlanningStrategy
    distance: float
    estimated_time: float
    energy_consumption: float  # Wh
    terrain_profile: List[Dict]
    status: PathStatus = PathStatus.PLANNED
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'waypoints': [w.to_dict() for w in self.waypoints],
            'strategy': self.strategy.value,
            'distance': self.distance,
            'estimated_time': self.estimated_time,
            'energy_consumption': self.energy_consumption,
            'terrain_profile': self.terrain_profile,
            'status': self.status.value,
            'created_at': self.created_at.isoformat(),
            'metadata': self.metadata
        }


@dataclass
class DroneConstraints:
    """Drone operational constraints"""
    max_speed: float = 20.0  # m/s
    max_altitude: float = 500.0  # meters
    min_altitude: float = 20.0  # meters
    max_climb_rate: float = 10.0  # m/s
    max_descent_rate: float = 5.0  # m/s
    max_flight_time: float = 1800.0  # seconds
    max_distance: float = 20000.0  # meters
    battery_capacity: float = 500.0  # Wh
    hover_power: float = 200.0  # W
    cruise_power: float = 150.0  # W
    climb_power: float = 300.0  # W


@dataclass
class PlanningResult:
    """Result of path planning operation"""
    success: bool
    path: Optional[PlannedPath]
    message: str
    alternatives: List[PlannedPath] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'success': self.success,
            'path': self.path.to_dict() if self.path else None,
            'message': self.message,
            'alternatives': [a.to_dict() for a in self.alternatives]
        }


class PathPlanner:
    """
    Main path planning orchestrator
    
    Features:
    - A* pathfinding
    - Terrain following
    - Energy optimization
    - Multi-objective planning
    """
    
    def __init__(
        self,
        terrain_processor: Optional[TerrainProcessor] = None,
        astar_planner: Optional[AStarPlanner] = None,
        constraints: Optional[DroneConstraints] = None
    ):
        """
        Initialize path planner
        
        Args:
            terrain_processor: Terrain analysis module
            astar_planner: A* pathfinding module
            constraints: Drone operational constraints
        """
        self.terrain_processor = terrain_processor or TerrainProcessor()
        self.astar = astar_planner or AStarPlanner()
        self.constraints = constraints or DroneConstraints()
        self._path_counter = 0
        
        logger.info(
            f"PathPlanner initialized - max_speed: {self.constraints.max_speed}m/s, "
            f"max_altitude: {self.constraints.max_altitude}m"
        )
    
    async def plan_path(
        self,
        start: Position,
        goal: Position,
        strategy: PlanningStrategy = PlanningStrategy.SHORTEST,
        obstacles: Optional[List[Obstacle]] = None,
        terrain: Optional[TerrainGrid] = None
    ) -> PlanningResult:
        """
        Plan a path from start to goal
        
        Args:
            start: Starting position
            goal: Goal position
            strategy: Planning strategy
            obstacles: List of obstacles to avoid
            terrain: Terrain data
            
        Returns:
            PlanningResult with planned path
        """
        logger.info(
            f"Planning path from {start.to_tuple()} to {goal.to_tuple()} "
            f"using {strategy.value} strategy"
        )
        
        # Validate inputs
        if not self._validate_positions(start, goal):
            return PlanningResult(
                success=False,
                path=None,
                message="Invalid start or goal position"
            )
        
        # Clear and add obstacles
        self.astar.clear_obstacles()
        if obstacles:
            self.astar.add_obstacles(obstacles)
        
        try:
            # Execute planning based on strategy
            if strategy == PlanningStrategy.SHORTEST:
                path = await self._plan_shortest(start, goal)
            elif strategy == PlanningStrategy.ENERGY_EFFICIENT:
                path = await self._plan_energy_efficient(start, goal, terrain)
            elif strategy == PlanningStrategy.TERRAIN_FOLLOWING:
                path = await self._plan_terrain_following(start, goal, terrain)
            elif strategy == PlanningStrategy.SAFETY_FIRST:
                path = await self._plan_safety_first(start, goal, terrain)
            else:
                path = await self._plan_shortest(start, goal)
            
            if not path:
                return PlanningResult(
                    success=False,
                    path=None,
                    message="No valid path found"
                )
            
            # Create planned path object
            planned_path = await self._create_planned_path(
                path, strategy, terrain
            )
            
            # Validate path
            if not self._validate_path(planned_path):
                return PlanningResult(
                    success=False,
                    path=None,
                    message="Generated path violates constraints"
                )
            
            logger.info(
                f"Path planned successfully: {len(path)} waypoints, "
                f"{planned_path.distance:.1f}m"
            )
            
            return PlanningResult(
                success=True,
                path=planned_path,
                message="Path planned successfully"
            )
            
        except Exception as e:
            logger.error(f"Path planning failed: {str(e)}")
            return PlanningResult(
                success=False,
                path=None,
                message=f"Planning error: {str(e)}"
            )
    
    async def _plan_shortest(
        self,
        start: Position,
        goal: Position
    ) -> Optional[List[Position]]:
        """Plan shortest path using A*"""
        path = await self.astar.search(start, goal)
        
        if path:
            # Smooth the path
            path = self.astar.smooth_path(path)
        
        return path
    
    async def _plan_energy_efficient(
        self,
        start: Position,
        goal: Position,
        terrain: Optional[TerrainGrid]
    ) -> Optional[List[Position]]:
        """Plan energy-efficient path"""
        # Get initial path
        path = await self.astar.search(start, goal)
        if not path:
            return None
        
        # Optimize for energy
        optimized_path = await self.optimize_energy(path, terrain)
        return optimized_path
    
    async def _plan_terrain_following(
        self,
        start: Position,
        goal: Position,
        terrain: Optional[TerrainGrid]
    ) -> Optional[List[Position]]:
        """Plan terrain-following path"""
        if not terrain:
            logger.warning("No terrain data for terrain following")
            return await self._plan_shortest(start, goal)
        
        path = await self.astar.search(start, goal)
        if not path:
            return None
        
        # Apply terrain following
        terrain_path = await self.terrain_following(path, terrain)
        return terrain_path
    
    async def _plan_safety_first(
        self,
        start: Position,
        goal: Position,
        terrain: Optional[TerrainGrid]
    ) -> Optional[List[Position]]:
        """Plan path with maximum safety margins"""
        # Use higher safety margin
        original_margin = self.terrain_processor.default_safety_margin
        self.terrain_processor.default_safety_margin = 50.0
        
        path = await self._plan_terrain_following(start, goal, terrain)
        
        # Restore original margin
        self.terrain_processor.default_safety_margin = original_margin
        
        return path
    
    async def astar_search(
        self,
        start: Position,
        goal: Position,
        timeout: float = 30.0
    ) -> Optional[List[Position]]:
        """
        Execute A* search
        
        Args:
            start: Starting position
            goal: Goal position
            timeout: Search timeout
            
        Returns:
            List of positions or None
        """
        return await self.astar.search(start, goal, timeout)
    
    async def terrain_following(
        self,
        path: List[Position],
        terrain: TerrainGrid,
        clearance: float = 30.0
    ) -> List[Position]:
        """
        Adjust path for terrain following
        
        Args:
            path: Original path
            terrain: Terrain data
            clearance: Minimum clearance above terrain
            
        Returns:
            Terrain-adjusted path
        """
        logger.info("Applying terrain following")
        
        adjusted_path = []
        
        for position in path:
            # Convert world coords to grid coords (simplified)
            grid_x = int(position.x / self.terrain_processor.grid_resolution)
            grid_y = int(position.y / self.terrain_processor.grid_resolution)
            
            # Get terrain elevation
            terrain_elevation = terrain.get_elevation(grid_x, grid_y)
            
            # Calculate safe altitude
            safe_altitude = max(
                position.z,
                terrain_elevation + clearance
            )
            
            # Apply constraints
            safe_altitude = min(safe_altitude, self.constraints.max_altitude)
            safe_altitude = max(safe_altitude, self.constraints.min_altitude)
            
            adjusted_path.append(Position(
                x=position.x,
                y=position.y,
                z=safe_altitude
            ))
        
        logger.debug(f"Terrain following applied to {len(adjusted_path)} waypoints")
        return adjusted_path
    
    async def optimize_energy(
        self,
        path: List[Position],
        terrain: Optional[TerrainGrid] = None
    ) -> List[Position]:
        """
        Optimize path for energy efficiency
        
        Args:
            path: Original path
            terrain: Optional terrain data
            
        Returns:
            Energy-optimized path
        """
        logger.info("Optimizing path for energy efficiency")
        
        if len(path) < 3:
            return path
        
        optimized = [path[0]]  # Keep start
        
        for i in range(1, len(path) - 1):
            prev = optimized[-1]
            curr = path[i]
            next_pos = path[i + 1]
            
            # Calculate altitude change
            altitude_change = curr.z - prev.z
            
            # Energy cost for climbing is higher
            if altitude_change > 0:
                # Prefer gradual climbs
                max_gradual_climb = self.constraints.max_climb_rate * 10  # over 10 seconds
                if altitude_change > max_gradual_climb:
                    # Interpolate intermediate point
                    mid_z = prev.z + max_gradual_climb
                    optimized.append(Position(curr.x, curr.y, mid_z))
            
            # Avoid unnecessary altitude changes
            avg_z = (prev.z + next_pos.z) / 2
            if abs(curr.z - avg_z) < 10:  # Within 10m of average
                # Use average altitude to reduce climbs/descents
                curr = Position(curr.x, curr.y, avg_z)
            
            optimized.append(curr)
        
        optimized.append(path[-1])  # Keep end
        
        logger.info(f"Energy optimization: {len(path)} -> {len(optimized)} waypoints")
        return optimized
    
    async def multi_goal_planning(
        self,
        start: Position,
        goals: List[Position],
        strategy: PlanningStrategy = PlanningStrategy.SHORTEST
    ) -> PlanningResult:
        """
        Plan path visiting multiple goals
        
        Args:
            start: Starting position
            goals: List of goal positions to visit
            strategy: Planning strategy
            
        Returns:
            PlanningResult with complete path
        """
        logger.info(f"Planning multi-goal path with {len(goals)} waypoints")
        
        if not goals:
            return PlanningResult(
                success=False,
                path=None,
                message="No goals provided"
            )
        
        # Solve using nearest neighbor heuristic
        remaining = goals.copy()
        current = start
        complete_path = [start]
        
        while remaining:
            # Find nearest unvisited goal
            nearest = min(
                remaining,
                key=lambda g: current.distance_to(g)
            )
            
            # Plan segment
            result = await self.plan_path(current, nearest, strategy)
            
            if not result.success:
                logger.warning(f"Failed to reach goal {nearest.to_tuple()}")
                remaining.remove(nearest)
                continue
            
            # Add segment path (excluding start)
            if result.path:
                for wp in result.path.waypoints[1:]:
                    complete_path.append(wp.position)
            
            remaining.remove(nearest)
            current = nearest
        
        # Create final planned path
        final_path = await self._create_planned_path(
            complete_path, strategy, None
        )
        
        return PlanningResult(
            success=True,
            path=final_path,
            message=f"Multi-goal path planned: {len(goals)} goals visited"
        )
    
    async def _create_planned_path(
        self,
        positions: List[Position],
        strategy: PlanningStrategy,
        terrain: Optional[TerrainGrid]
    ) -> PlannedPath:
        """Create PlannedPath object from positions"""
        # Generate path ID
        self._path_counter += 1
        path_id = f"path_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{self._path_counter}"
        
        # Convert positions to waypoints
        waypoints = []
        for i, pos in enumerate(positions):
            is_checkpoint = (i == 0 or i == len(positions) - 1)
            waypoint = Waypoint(
                position=pos,
                speed=self.constraints.max_speed * 0.7,  # Conservative speed
                is_checkpoint=is_checkpoint
            )
            waypoints.append(waypoint)
        
        # Calculate metrics
        distance = self.astar.calculate_path_length(positions)
        estimated_time = await self._estimate_flight_time(waypoints)
        energy_consumption = await self._estimate_energy(
            positions, estimated_time
        )
        
        # Generate terrain profile
        terrain_profile = []
        if terrain:
            terrain_profile = [
                {
                    'position': pos.to_tuple(),
                    'elevation': terrain.get_elevation(
                        int(pos.x / self.terrain_processor.grid_resolution),
                        int(pos.y / self.terrain_processor.grid_resolution)
                    )
                }
                for pos in positions
            ]
        
        return PlannedPath(
            id=path_id,
            waypoints=waypoints,
            strategy=strategy,
            distance=distance,
            estimated_time=estimated_time,
            energy_consumption=energy_consumption,
            terrain_profile=terrain_profile
        )
    
    async def _estimate_flight_time(self, waypoints: List[Waypoint]) -> float:
        """Estimate total flight time"""
        total_time = 0.0
        
        for i in range(len(waypoints) - 1):
            distance = waypoints[i].position.distance_to(waypoints[i + 1].position)
            avg_speed = (waypoints[i].speed + waypoints[i + 1].speed) / 2
            segment_time = distance / avg_speed if avg_speed > 0 else 0
            total_time += segment_time
            total_time += waypoints[i + 1].hold_time
        
        return total_time
    
    async def _estimate_energy(
        self,
        positions: List[Position],
        flight_time: float
    ) -> float:
        """Estimate energy consumption"""
        # Base cruise energy
        cruise_energy = (
            self.constraints.cruise_power * 
            flight_time / 3600  # Convert to Wh
        )
        
        # Additional energy for climbs
        climb_energy = 0.0
        for i in range(len(positions) - 1):
            altitude_change = positions[i + 1].z - positions[i].z
            if altitude_change > 0:
                distance = positions[i].distance_to(positions[i + 1])
                climb_time = distance / self.constraints.max_speed
                climb_energy += (
                    (self.constraints.climb_power - self.constraints.cruise_power) *
                    climb_time / 3600
                )
        
        total_energy = cruise_energy + climb_energy
        
        # Add 20% safety margin
        return total_energy * 1.2
    
    def _validate_positions(self, start: Position, goal: Position) -> bool:
        """Validate start and goal positions"""
        # Check altitude constraints
        if not (0 <= start.z <= self.constraints.max_altitude):
            logger.error(f"Invalid start altitude: {start.z}m")
            return False
        
        if not (0 <= goal.z <= self.constraints.max_altitude):
            logger.error(f"Invalid goal altitude: {goal.z}m")
            return False
        
        # Check distance constraint
        distance = start.distance_to(goal)
        if distance > self.constraints.max_distance:
            logger.error(f"Distance {distance}m exceeds maximum {self.constraints.max_distance}m")
            return False
        
        return True
    
    def _validate_path(self, path: PlannedPath) -> bool:
        """Validate complete path against constraints"""
        # Check flight time
        if path.estimated_time > self.constraints.max_flight_time:
            logger.error(
                f"Flight time {path.estimated_time}s exceeds maximum "
                f"{self.constraints.max_flight_time}s"
            )
            return False
        
        # Check energy
        if path.energy_consumption > self.constraints.battery_capacity:
            logger.error(
                f"Energy {path.energy_consumption}Wh exceeds capacity "
                f"{self.constraints.battery_capacity}Wh"
            )
            return False
        
        # Check altitude constraints
        for waypoint in path.waypoints:
            if not (self.constraints.min_altitude <= waypoint.position.z 
                    <= self.constraints.max_altitude):
                logger.error(f"Waypoint altitude {waypoint.position.z}m out of bounds")
                return False
        
        return True
    
    def get_path_statistics(self, path: PlannedPath) -> Dict[str, Any]:
        """Get detailed path statistics"""
        waypoints = path.waypoints
        
        # Calculate altitude statistics
        altitudes = [wp.position.z for wp in waypoints]
        
        # Calculate speed statistics
        speeds = [wp.speed for wp in waypoints]
        
        return {
            'num_waypoints': len(waypoints),
            'num_checkpoints': sum(1 for wp in waypoints if wp.is_checkpoint),
            'total_distance': path.distance,
            'estimated_time': path.estimated_time,
            'energy_consumption': path.energy_consumption,
            'altitude_min': min(altitudes),
            'altitude_max': max(altitudes),
            'altitude_avg': sum(altitudes) / len(altitudes),
            'speed_min': min(speeds),
            'speed_max': max(speeds),
            'speed_avg': sum(speeds) / len(speeds)
        }
