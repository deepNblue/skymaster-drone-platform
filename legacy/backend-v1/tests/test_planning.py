"""
SkyMaster Path Planning Module - Unit Tests
"""

import asyncio
import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from core.planning import AStarPlanner, PathPlanner, TerrainProcessor
from core.planning.astar import Position, Obstacle, ObstacleType
from core.planning.path_planner import PlanningStrategy, DroneConstraints
from core.planning.terrain import TerrainType


class TestAStarPlanner:
    """Test A* pathfinding algorithm"""
    
    @pytest.fixture
    def planner(self):
        return AStarPlanner(grid_resolution=1.0)
    
    def test_position_creation(self):
        """Test Position class"""
        pos = Position(x=10.0, y=20.0, z=30.0)
        assert pos.x == 10.0
        assert pos.y == 20.0
        assert pos.z == 30.0
        
        # Test distance calculation
        pos2 = Position(x=13.0, y=24.0, z=30.0)
        distance = pos.distance_to(pos2)
        assert abs(distance - 5.0) < 0.01  # 3-4-5 triangle
    
    def test_obstacle_creation(self):
        """Test Obstacle class"""
        obs = Obstacle(
            position=Position(x=50, y=50, z=0),
            radius=10,
            height=100,
            obstacle_type=ObstacleType.STATIC,
            safety_margin=5.0
        )
        assert obs.radius == 10
        assert obs.safety_margin == 5.0
        
        # Test collision detection
        inside = Position(x=55, y=55, z=50)
        assert obs.contains_point(inside) is True
        
        outside = Position(x=100, y=100, z=50)
        assert obs.contains_point(outside) is False
    
    def test_heuristic(self, planner):
        """Test heuristic function"""
        start = Position(x=0, y=0, z=0)
        goal = Position(x=30, y=40, z=0)
        
        heuristic = planner.heuristic(start, goal)
        assert abs(heuristic - 50.0) < 0.01  # 3-4-5 triangle
    
    def test_neighbors(self, planner):
        """Test neighbor generation"""
        pos = Position(x=10, y=10, z=50)
        neighbors = planner.get_neighbors(pos)
        
        assert len(neighbors) > 0
        # Check that all neighbors are different
        neighbor_set = set(n.to_tuple() for n in neighbors)
        assert len(neighbor_set) == len(neighbors)
    
    @pytest.mark.asyncio
    async def test_simple_path(self, planner):
        """Test simple path finding"""
        start = Position(x=0, y=0, z=50)
        goal = Position(x=10, y=10, z=50)
        
        path = await planner.search(start, goal)
        
        assert path is not None
        assert len(path) > 0
        assert path[0] == start
        assert path[-1].distance_to(goal) < planner.grid_resolution * 2
    
    @pytest.mark.asyncio
    async def test_path_with_obstacle(self, planner):
        """Test path finding with obstacles"""
        start = Position(x=0, y=0, z=50)
        goal = Position(x=20, y=0, z=50)
        
        # Add obstacle in direct path
        obstacle = Obstacle(
            position=Position(x=10, y=0, z=50),
            radius=5,
            height=20,
            obstacle_type=ObstacleType.STATIC
        )
        planner.add_obstacle(obstacle)
        
        path = await planner.search(start, goal)
        
        assert path is not None
        # Path should avoid obstacle
        for point in path:
            assert not obstacle.contains_point(point)
    
    def test_path_smoothing(self, planner):
        """Test path smoothing"""
        # Create a zigzag path
        path = [
            Position(x=0, y=0, z=50),
            Position(x=5, y=10, z=50),
            Position(x=10, y=0, z=50),
            Position(x=15, y=10, z=50),
            Position(x=20, y=0, z=50)
        ]
        
        smoothed = planner.smooth_path(path, iterations=3)
        
        assert len(smoothed) == len(path)
        # Start and end should remain unchanged
        assert smoothed[0] == path[0]
        assert smoothed[-1] == path[-1]
    
    def test_path_length(self, planner):
        """Test path length calculation"""
        path = [
            Position(x=0, y=0, z=0),
            Position(x=3, y=4, z=0),
            Position(x=6, y=8, z=0)
        ]
        
        length = planner.calculate_path_length(path)
        assert abs(length - 10.0) < 0.01  # Two 5-unit segments


class TestTerrainProcessor:
    """Test terrain processing"""
    
    @pytest.fixture
    def processor(self):
        return TerrainProcessor(
            default_safety_margin=30.0,
            grid_resolution=10.0
        )
    
    @pytest.mark.asyncio
    async def test_terrain_generation(self, processor):
        """Test terrain grid generation"""
        bounds = (39.9, 116.3, 40.0, 116.4)  # Beijing area
        terrain = await processor.get_elevation_data(bounds)
        
        assert terrain is not None
        assert terrain.elevations is not None
        assert terrain.shape[0] > 0
        assert terrain.shape[1] > 0
    
    def test_slope_calculation(self, processor):
        """Test slope calculation"""
        # Create simple terrain grid
        import numpy as np
        from core.planning.terrain import TerrainGrid
        
        terrain = TerrainGrid(
            origin_lat=40.0,
            origin_lon=116.0,
            resolution=10.0,
            elevations=np.array([
                [100, 100, 100],
                [100, 150, 100],
                [100, 100, 100]
            ], dtype=np.float32),
            terrain_types=np.full((3, 3), TerrainType.FLAT.value, dtype=object)
        )
        
        slope = terrain.get_slope(1, 1)
        assert slope > 0  # Center should have slope due to elevation difference
    
    def test_safe_altitude_check(self, processor):
        """Test safe altitude checking"""
        import numpy as np
        from core.planning.terrain import TerrainGrid
        
        terrain = TerrainGrid(
            origin_lat=40.0,
            origin_lon=116.0,
            resolution=10.0,
            elevations=np.ones((10, 10), dtype=np.float32) * 100,  # 100m elevation
            terrain_types=np.full((10, 10), TerrainType.FLAT.value, dtype=object)
        )
        
        # Safe altitude
        is_safe, clearance = processor.check_safe_altitude(
            terrain, 5, 5, altitude=150.0
        )
        assert is_safe is True
        assert clearance == 50.0
        
        # Unsafe altitude
        is_safe, clearance = processor.check_safe_altitude(
            terrain, 5, 5, altitude=120.0
        )
        assert is_safe is False
        assert clearance == 20.0
    
    def test_minimum_safe_altitude(self, processor):
        """Test minimum safe altitude calculation"""
        import numpy as np
        from core.planning.terrain import TerrainGrid
        
        terrain = TerrainGrid(
            origin_lat=40.0,
            origin_lon=116.0,
            resolution=10.0,
            elevations=np.array([
                [90, 95, 100],
                [95, 150, 105],
                [100, 105, 110]
            ], dtype=np.float32),
            terrain_types=np.full((3, 3), TerrainType.FLAT.value, dtype=object)
        )
        
        min_safe = processor.get_minimum_safe_altitude(terrain, 1, 1, radius=1)
        # Should be max elevation (150) + safety margin (30)
        assert min_safe == 180.0


class TestPathPlanner:
    """Test main path planner"""
    
    @pytest.fixture
    def planner(self):
        return PathPlanner()
    
    @pytest.mark.asyncio
    async def test_shortest_path(self, planner):
        """Test shortest path planning"""
        start = Position(x=0, y=0, z=50)
        goal = Position(x=100, y=100, z=60)
        
        result = await planner.plan_path(
            start=start,
            goal=goal,
            strategy=PlanningStrategy.SHORTEST
        )
        
        assert result.success is True
        assert result.path is not None
        assert result.path.distance > 0
        assert result.path.estimated_time > 0
        assert result.path.energy_consumption > 0
    
    @pytest.mark.asyncio
    async def test_energy_efficient_path(self, planner):
        """Test energy-efficient path planning"""
        start = Position(x=0, y=0, z=50)
        goal = Position(x=100, y=100, z=60)
        
        result = await planner.plan_path(
            start=start,
            goal=goal,
            strategy=PlanningStrategy.ENERGY_EFFICIENT
        )
        
        assert result.success is True
        assert result.path is not None
    
    @pytest.mark.asyncio
    async def test_terrain_following(self, planner):
        """Test terrain following"""
        from core.planning.terrain import TerrainGrid
        import numpy as np
        
        # Create simple terrain
        terrain = TerrainGrid(
            origin_lat=40.0,
            origin_lon=116.0,
            resolution=10.0,
            elevations=np.ones((20, 20), dtype=np.float32) * 100,
            terrain_types=np.full((20, 20), TerrainType.FLAT.value, dtype=object)
        )
        
        start = Position(x=0, y=0, z=50)
        goal = Position(x=100, y=100, z=60)
        
        result = await planner.plan_path(
            start=start,
            goal=goal,
            strategy=PlanningStrategy.TERRAIN_FOLLOWING,
            terrain=terrain
        )
        
        assert result.success is True
        assert result.path is not None
    
    @pytest.mark.asyncio
    async def test_multi_goal_planning(self, planner):
        """Test multi-goal path planning"""
        start = Position(x=0, y=0, z=50)
        goals = [
            Position(x=50, y=50, z=55),
            Position(x=100, y=50, z=60),
            Position(x=100, y=100, z=65)
        ]
        
        result = await planner.multi_goal_planning(
            start=start,
            goals=goals,
            strategy=PlanningStrategy.SHORTEST
        )
        
        assert result.success is True
        assert result.path is not None
        assert result.path.waypoints[0].position == start
    
    def test_position_validation(self, planner):
        """Test position validation"""
        # Valid positions
        valid_start = Position(x=0, y=0, z=50)
        valid_goal = Position(x=100, y=100, z=60)
        assert planner._validate_positions(valid_start, valid_goal) is True
        
        # Invalid altitude
        invalid_alt = Position(x=0, y=0, z=600)
        assert planner._validate_positions(invalid_alt, valid_goal) is False
        
        # Too far
        far_goal = Position(x=50000, y=50000, z=60)
        assert planner._validate_positions(valid_start, far_goal) is False
    
    def test_path_statistics(self, planner):
        """Test path statistics generation"""
        from core.planning.path_planner import PlannedPath, Waypoint
        
        # Create mock path
        waypoints = [
            Waypoint(position=Position(x=0, y=0, z=50), speed=15.0),
            Waypoint(position=Position(x=50, y=50, z=55), speed=15.0),
            Waypoint(position=Position(x=100, y=100, z=60), speed=15.0)
        ]
        
        path = PlannedPath(
            id="test_path",
            waypoints=waypoints,
            strategy=PlanningStrategy.SHORTEST,
            distance=141.42,
            estimated_time=10.0,
            energy_consumption=0.5,
            terrain_profile=[]
        )
        
        stats = planner.get_path_statistics(path)
        
        assert stats['num_waypoints'] == 3
        assert stats['altitude_min'] == 50.0
        assert stats['altitude_max'] == 60.0
        assert stats['speed_avg'] == 15.0


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
