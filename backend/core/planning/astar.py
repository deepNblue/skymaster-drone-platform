"""
SkyMaster Drone Platform - A* Path Planning Algorithm
Implements A* search with heuristic functions and path smoothing
"""

import asyncio
import heapq
import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class ObstacleType(Enum):
    """Types of obstacles in the environment"""
    STATIC = "static"
    DYNAMIC = "dynamic"
    RESTRICTED_ZONE = "restricted_zone"
    NO_FLY_ZONE = "no_fly_zone"


@dataclass
class Position:
    """3D position with altitude"""
    x: float
    y: float
    z: float = 0.0
    
    def __hash__(self):
        return hash((round(self.x, 2), round(self.y, 2), round(self.z, 2)))
    
    def __eq__(self, other):
        if not isinstance(other, Position):
            return False
        return (
            abs(self.x - other.x) < 0.01 and
            abs(self.y - other.y) < 0.01 and
            abs(self.z - other.z) < 0.01
        )
    
    def distance_to(self, other: 'Position') -> float:
        """Calculate Euclidean distance to another position"""
        return math.sqrt(
            (self.x - other.x) ** 2 +
            (self.y - other.y) ** 2 +
            (self.z - other.z) ** 2
        )
    
    def to_tuple(self) -> Tuple[float, float, float]:
        """Convert to tuple representation"""
        return (self.x, self.y, self.z)
    
    @classmethod
    def from_tuple(cls, coords: Tuple[float, float, float]) -> 'Position':
        """Create Position from tuple"""
        return cls(x=coords[0], y=coords[1], z=coords[2])


@dataclass
class Obstacle:
    """Obstacle definition"""
    position: Position
    radius: float
    height: float
    obstacle_type: ObstacleType
    safety_margin: float = 5.0
    
    def contains_point(self, point: Position) -> bool:
        """Check if a point is within the obstacle boundary"""
        horizontal_dist = math.sqrt(
            (point.x - self.position.x) ** 2 +
            (point.y - self.position.y) ** 2
        )
        return (
            horizontal_dist <= (self.radius + self.safety_margin) and
            self.position.z <= point.z <= (self.position.z + self.height)
        )


@dataclass(order=True)
class Node:
    """A* search node"""
    f_score: float
    position: Position = field(compare=False)
    g_score: float = field(compare=False)
    parent: Optional['Node'] = field(default=None, compare=False)
    
    def __hash__(self):
        return hash(self.position)
    
    def __eq__(self, other):
        if not isinstance(other, Node):
            return False
        return self.position == other.position


class AStarPlanner:
    """
    A* path planning algorithm implementation
    
    Features:
    - Configurable heuristic functions
    - Obstacle avoidance
    - Path smoothing
    - 3D navigation support
    """
    
    def __init__(
        self,
        grid_resolution: float = 1.0,
        heuristic_weight: float = 1.0,
        max_iterations: int = 100000,
        diagonal_movement: bool = True
    ):
        """
        Initialize A* planner
        
        Args:
            grid_resolution: Grid cell size in meters
            heuristic_weight: Weight for heuristic (1.0 = standard A*)
            max_iterations: Maximum search iterations
            diagonal_movement: Allow diagonal movement
        """
        self.grid_resolution = grid_resolution
        self.heuristic_weight = heuristic_weight
        self.max_iterations = max_iterations
        self.diagonal_movement = diagonal_movement
        self.obstacles: List[Obstacle] = []
        self._obstacle_cache: Set[Tuple[int, int, int]] = set()
        
        logger.info(
            f"AStarPlanner initialized - resolution: {grid_resolution}m, "
            f"heuristic_weight: {heuristic_weight}"
        )
    
    def add_obstacle(self, obstacle: Obstacle) -> None:
        """Add an obstacle to the planning space"""
        self.obstacles.append(obstacle)
        self._update_obstacle_cache(obstacle)
        logger.debug(f"Added obstacle at {obstacle.position.to_tuple()}")
    
    def add_obstacles(self, obstacles: List[Obstacle]) -> None:
        """Add multiple obstacles"""
        for obstacle in obstacles:
            self.add_obstacle(obstacle)
    
    def clear_obstacles(self) -> None:
        """Clear all obstacles"""
        self.obstacles.clear()
        self._obstacle_cache.clear()
        logger.debug("All obstacles cleared")
    
    def _update_obstacle_cache(self, obstacle: Obstacle) -> None:
        """Update obstacle cache for faster collision checking"""
        grid_radius = int((obstacle.radius + obstacle.safety_margin) / self.grid_resolution)
        center_grid = self._world_to_grid(obstacle.position)
        
        for dx in range(-grid_radius, grid_radius + 1):
            for dy in range(-grid_radius, grid_radius + 1):
                for dz in range(-2, 3):
                    if dx * dx + dy * dy <= grid_radius * grid_radius:
                        self._obstacle_cache.add((
                            center_grid[0] + dx,
                            center_grid[1] + dy,
                            center_grid[2] + dz
                        ))
    
    def _world_to_grid(self, position: Position) -> Tuple[int, int, int]:
        """Convert world coordinates to grid coordinates"""
        return (
            int(position.x / self.grid_resolution),
            int(position.y / self.grid_resolution),
            int(position.z / self.grid_resolution)
        )
    
    def _grid_to_world(self, grid_pos: Tuple[int, int, int]) -> Position:
        """Convert grid coordinates to world coordinates"""
        return Position(
            x=grid_pos[0] * self.grid_resolution,
            y=grid_pos[1] * self.grid_resolution,
            z=grid_pos[2] * self.grid_resolution
        )
    
    def heuristic(self, current: Position, goal: Position) -> float:
        """
        Calculate heuristic cost (Euclidean distance)
        
        Args:
            current: Current position
            goal: Goal position
            
        Returns:
            Heuristic cost estimate
        """
        return current.distance_to(goal) * self.heuristic_weight
    
    def get_neighbors(self, position: Position) -> List[Position]:
        """
        Get valid neighboring positions
        
        Args:
            position: Current position
            
        Returns:
            List of valid neighboring positions
        """
        neighbors = []
        grid_pos = self._world_to_grid(position)
        
        # Movement directions
        directions = [
            (1, 0, 0), (-1, 0, 0),  # X-axis
            (0, 1, 0), (0, -1, 0),  # Y-axis
            (0, 0, 1), (0, 0, -1),  # Z-axis
        ]
        
        if self.diagonal_movement:
            directions.extend([
                (1, 1, 0), (1, -1, 0), (-1, 1, 0), (-1, -1, 0),  # XY diagonal
                (1, 0, 1), (1, 0, -1), (-1, 0, 1), (-1, 0, -1),  # XZ diagonal
                (0, 1, 1), (0, 1, -1), (0, -1, 1), (0, -1, -1),  # YZ diagonal
                (1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1),  # XYZ diagonal
                (-1, 1, 1), (-1, 1, -1), (-1, -1, 1), (-1, -1, -1),
            ])
        
        for dx, dy, dz in directions:
            new_grid = (grid_pos[0] + dx, grid_pos[1] + dy, grid_pos[2] + dz)
            
            # Check obstacle collision
            if new_grid in self._obstacle_cache:
                continue
            
            # Check altitude limits (0-500m)
            new_z = new_grid[2] * self.grid_resolution
            if not (0 <= new_z <= 500):
                continue
            
            neighbors.append(self._grid_to_world(new_grid))
        
        return neighbors
    
    def movement_cost(self, from_pos: Position, to_pos: Position) -> float:
        """
        Calculate movement cost between two positions
        
        Args:
            from_pos: Starting position
            to_pos: Target position
            
        Returns:
            Movement cost
        """
        distance = from_pos.distance_to(to_pos)
        
        # Add penalty for altitude changes
        altitude_change = abs(to_pos.z - from_pos.z)
        altitude_penalty = altitude_change * 0.5
        
        return distance + altitude_penalty
    
    async def search(
        self,
        start: Position,
        goal: Position,
        timeout: float = 30.0
    ) -> Optional[List[Position]]:
        """
        Perform A* search from start to goal
        
        Args:
            start: Starting position
            goal: Goal position
            timeout: Maximum search time in seconds
            
        Returns:
            List of positions forming the path, or None if no path found
        """
        logger.info(f"Starting A* search from {start.to_tuple()} to {goal.to_tuple()}")
        
        # Initialize
        open_set: List[Node] = []
        closed_set: Set[Position] = set()
        g_scores: Dict[Position, float] = {start: 0.0}
        
        # Add start node
        start_node = Node(
            f_score=self.heuristic(start, goal),
            position=start,
            g_score=0.0
        )
        heapq.heappush(open_set, start_node)
        
        iterations = 0
        
        try:
            await asyncio.wait_for(
                self._search_loop(
                    open_set, closed_set, g_scores, goal, iterations
                ),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"A* search timed out after {timeout}s")
            return None
        
        # Check if we found a path
        if not open_set:
            logger.warning("No path found")
            return None
        
        # Reconstruct path
        current = open_set[0]
        if current.position.distance_to(goal) > self.grid_resolution * 2:
            logger.warning("Goal not reached")
            return None
        
        path = self._reconstruct_path(current)
        logger.info(f"Path found with {len(path)} waypoints")
        
        return path
    
    async def _search_loop(
        self,
        open_set: List[Node],
        closed_set: Set[Position],
        g_scores: Dict[Position, float],
        goal: Position,
        iterations: int
    ) -> None:
        """Main search loop"""
        while open_set and iterations < self.max_iterations:
            iterations += 1
            
            # Yield control periodically
            if iterations % 1000 == 0:
                await asyncio.sleep(0)
            
            current = heapq.heappop(open_set)
            
            # Check if goal reached
            if current.position.distance_to(goal) < self.grid_resolution:
                heapq.heappush(open_set, current)
                return
            
            closed_set.add(current.position)
            
            # Expand neighbors
            for neighbor_pos in self.get_neighbors(current.position):
                if neighbor_pos in closed_set:
                    continue
                
                tentative_g = current.g_score + self.movement_cost(
                    current.position, neighbor_pos
                )
                
                if neighbor_pos not in g_scores or tentative_g < g_scores[neighbor_pos]:
                    g_scores[neighbor_pos] = tentative_g
                    f_score = tentative_g + self.heuristic(neighbor_pos, goal)
                    
                    neighbor_node = Node(
                        f_score=f_score,
                        position=neighbor_pos,
                        g_score=tentative_g,
                        parent=current
                    )
                    heapq.heappush(open_set, neighbor_node)
    
    def _reconstruct_path(self, node: Node) -> List[Position]:
        """Reconstruct path from goal node to start"""
        path = []
        current: Optional[Node] = node
        
        while current is not None:
            path.append(current.position)
            current = current.parent
        
        path.reverse()
        return path
    
    def smooth_path(
        self,
        path: List[Position],
        iterations: int = 3,
        weight: float = 0.5
    ) -> List[Position]:
        """
        Smooth path using gradient descent
        
        Args:
            path: Original path
            iterations: Number of smoothing iterations
            weight: Smoothing weight (0-1)
            
        Returns:
            Smoothed path
        """
        if len(path) <= 2:
            return path
        
        logger.debug(f"Smoothing path with {iterations} iterations")
        
        smoothed = [Position(p.x, p.y, p.z) for p in path]
        
        for _ in range(iterations):
            new_path = [smoothed[0]]  # Keep start fixed
            
            for i in range(1, len(smoothed) - 1):
                prev_pos = new_path[i - 1]
                curr_pos = smoothed[i]
                next_pos = smoothed[i + 1]
                
                # Gradient descent smoothing
                new_x = curr_pos.x + weight * (
                    prev_pos.x + next_pos.x - 2 * curr_pos.x
                )
                new_y = curr_pos.y + weight * (
                    prev_pos.y + next_pos.y - 2 * curr_pos.y
                )
                new_z = curr_pos.z + weight * (
                    prev_pos.z + next_pos.z - 2 * curr_pos.z
                )
                
                new_pos = Position(new_x, new_y, new_z)
                
                # Check collision with obstacles
                if not self._check_path_collision(new_path[-1], new_pos):
                    new_path.append(new_pos)
                else:
                    new_path.append(curr_pos)
            
            new_path.append(smoothed[-1])  # Keep end fixed
            smoothed = new_path
        
        logger.debug(f"Smoothed path: {len(path)} -> {len(smoothed)} waypoints")
        return smoothed
    
    def _check_path_collision(
        self,
        start: Position,
        end: Position,
        samples: int = 10
    ) -> bool:
        """Check if path segment collides with obstacles"""
        for i in range(samples + 1):
            t = i / samples
            point = Position(
                x=start.x + t * (end.x - start.x),
                y=start.y + t * (end.y - start.y),
                z=start.z + t * (end.z - start.z)
            )
            
            grid_pos = self._world_to_grid(point)
            if grid_pos in self._obstacle_cache:
                return True
        
        return False
    
    def calculate_path_length(self, path: List[Position]) -> float:
        """Calculate total path length"""
        if len(path) < 2:
            return 0.0
        
        total_length = 0.0
        for i in range(len(path) - 1):
            total_length += path[i].distance_to(path[i + 1])
        
        return total_length
