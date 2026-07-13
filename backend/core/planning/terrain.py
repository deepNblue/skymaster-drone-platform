"""
SkyMaster Drone Platform - Terrain Processing Module
Handles elevation data, terrain analysis, and safety checks
"""

import asyncio
import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class TerrainType(Enum):
    """Terrain classification types"""
    FLAT = "flat"
    HILLY = "hilly"
    MOUNTAINOUS = "mountainous"
    WATER = "water"
    URBAN = "urban"
    FOREST = "forest"


@dataclass
class TerrainPoint:
    """Single terrain data point"""
    latitude: float
    longitude: float
    elevation: float
    terrain_type: TerrainType = TerrainType.FLAT
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'elevation': self.elevation,
            'terrain_type': self.terrain_type.value
        }


@dataclass
class TerrainGrid:
    """Grid-based terrain representation"""
    origin_lat: float
    origin_lon: float
    resolution: float  # meters per cell
    elevations: np.ndarray
    terrain_types: np.ndarray
    
    @property
    def shape(self) -> Tuple[int, int]:
        """Get grid shape"""
        return self.elevations.shape
    
    def get_elevation(self, x: int, y: int) -> float:
        """Get elevation at grid position"""
        if 0 <= x < self.elevations.shape[0] and 0 <= y < self.elevations.shape[1]:
            return float(self.elevations[x, y])
        return 0.0
    
    def get_slope(self, x: int, y: int) -> float:
        """Calculate slope at grid position (degrees)"""
        if not (1 <= x < self.elevations.shape[0] - 1 and 
                1 <= y < self.elevations.shape[1] - 1):
            return 0.0
        
        # Calculate gradient using Sobel operator
        dx = (self.elevations[x + 1, y] - self.elevations[x - 1, y]) / (2 * self.resolution)
        dy = (self.elevations[x, y + 1] - self.elevations[x, y - 1]) / (2 * self.resolution)
        
        slope_rad = math.atan(math.sqrt(dx * dx + dy * dy))
        return math.degrees(slope_rad)


class TerrainProcessor:
    """
    Terrain analysis and processing system
    
    Features:
    - Elevation data management
    - Terrain grid generation
    - Slope calculation
    - Safety altitude checking
    """
    
    def __init__(
        self,
        default_safety_margin: float = 30.0,
        grid_resolution: float = 10.0,
        max_slope_angle: float = 45.0
    ):
        """
        Initialize terrain processor
        
        Args:
            default_safety_margin: Minimum height above terrain (meters)
            grid_resolution: Terrain grid resolution (meters per cell)
            max_slope_angle: Maximum safe slope angle (degrees)
        """
        self.default_safety_margin = default_safety_margin
        self.grid_resolution = grid_resolution
        self.max_slope_angle = max_slope_angle
        self._terrain_cache: Dict[str, TerrainGrid] = {}
        
        logger.info(
            f"TerrainProcessor initialized - safety_margin: {default_safety_margin}m, "
            f"resolution: {grid_resolution}m"
        )
    
    async def get_elevation_data(
        self,
        bounds: Tuple[float, float, float, float],
        source: str = "srtm"
    ) -> TerrainGrid:
        """
        Fetch elevation data for a geographic region
        
        Args:
            bounds: (min_lat, min_lon, max_lat, max_lon)
            source: Elevation data source
            
        Returns:
            TerrainGrid with elevation data
        """
        min_lat, min_lon, max_lat, max_lon = bounds
        
        logger.info(
            f"Fetching elevation data for bounds: "
            f"lat=[{min_lat}, {max_lat}], lon=[{min_lon}, {max_lon}]"
        )
        
        # Calculate grid dimensions
        lat_diff = max_lat - min_lat
        lon_diff = max_lon - min_lon
        
        # Approximate meters per degree (varies by latitude)
        meters_per_deg_lat = 111000
        meters_per_deg_lon = 111000 * math.cos(math.radians((min_lat + max_lat) / 2))
        
        width = int((lon_diff * meters_per_deg_lon) / self.grid_resolution)
        height = int((lat_diff * meters_per_deg_lat) / self.grid_resolution)
        
        # Generate synthetic terrain data (in production, fetch from actual source)
        elevations = await self._generate_synthetic_terrain(height, width, bounds)
        terrain_types = np.full((height, width), TerrainType.FLAT.value, dtype=object)
        
        # Classify terrain
        terrain_types = self._classify_terrain(elevations, terrain_types)
        
        terrain_grid = TerrainGrid(
            origin_lat=min_lat,
            origin_lon=min_lon,
            resolution=self.grid_resolution,
            elevations=elevations,
            terrain_types=terrain_types
        )
        
        # Cache the terrain data
        cache_key = f"{min_lat}_{min_lon}_{max_lat}_{max_lon}"
        self._terrain_cache[cache_key] = terrain_grid
        
        logger.info(f"Generated terrain grid: {width}x{height} cells")
        return terrain_grid
    
    async def _generate_synthetic_terrain(
        self,
        height: int,
        width: int,
        bounds: Tuple[float, float, float, float]
    ) -> np.ndarray:
        """
        Generate synthetic terrain using Perlin-like noise
        
        In production, this would fetch real elevation data from sources like:
        - SRTM (Shuttle Radar Topography Mission)
        - ASTER GDEM
        - LiDAR surveys
        """
        await asyncio.sleep(0)  # Simulate async operation
        
        # Create base elevation using multiple octaves
        elevations = np.zeros((height, width), dtype=np.float32)
        
        # Generate terrain using fractal noise
        for octave in range(4):
            freq = 2 ** octave
            amp = 100 / freq  # meters
            
            x = np.linspace(0, freq * 2, width)
            y = np.linspace(0, freq * 2, height)
            X, Y = np.meshgrid(x, y)
            
            # Simple sinusoidal terrain (replace with Perlin noise in production)
            noise = amp * (
                np.sin(X * math.pi) * np.cos(Y * math.pi) +
                0.5 * np.sin(X * 2 * math.pi) * np.cos(Y * 2 * math.pi)
            )
            elevations += noise
        
        # Add base elevation (e.g., sea level + regional elevation)
        base_elevation = 100  # meters
        elevations += base_elevation
        
        return elevations
    
    def _classify_terrain(
        self,
        elevations: np.ndarray,
        terrain_types: np.ndarray
    ) -> np.ndarray:
        """Classify terrain based on elevation and slope"""
        # Calculate gradient magnitude
        grad_x = np.gradient(elevations, axis=1)
        grad_y = np.gradient(elevations, axis=0)
        gradient_mag = np.sqrt(grad_x ** 2 + grad_y ** 2)
        
        # Classify based on elevation variance and gradient
        for i in range(elevations.shape[0]):
            for j in range(elevations.shape[1]):
                if elevations[i, j] < 0:
                    terrain_types[i, j] = TerrainType.WATER.value
                elif gradient_mag[i, j] > 30:
                    terrain_types[i, j] = TerrainType.MOUNTAINOUS.value
                elif gradient_mag[i, j] > 15:
                    terrain_types[i, j] = TerrainType.HILLY.value
                elif gradient_mag[i, j] > 5:
                    terrain_types[i, j] = TerrainType.FLAT.value
        
        return terrain_types
    
    def calculate_slope(
        self,
        terrain: TerrainGrid,
        x: int,
        y: int,
        direction: Optional[Tuple[float, float]] = None
    ) -> float:
        """
        Calculate slope at a specific point
        
        Args:
            terrain: Terrain grid
            x: X coordinate
            y: Y coordinate
            direction: Optional direction vector for directional slope
            
        Returns:
            Slope in degrees
        """
        slope = terrain.get_slope(x, y)
        
        if direction is not None:
            # Calculate directional slope
            dx, dy = direction
            grad_x = (terrain.get_elevation(x + 1, y) - 
                     terrain.get_elevation(x - 1, y)) / (2 * self.grid_resolution)
            grad_y = (terrain.get_elevation(x, y + 1) - 
                     terrain.get_elevation(x, y - 1)) / (2 * self.grid_resolution)
            
            # Dot product with direction
            directional_grad = grad_x * dx + grad_y * dy
            slope = math.degrees(math.atan(directional_grad))
        
        return slope
    
    def check_safe_altitude(
        self,
        terrain: TerrainGrid,
        x: int,
        y: int,
        altitude: float,
        safety_margin: Optional[float] = None
    ) -> Tuple[bool, float]:
        """
        Check if altitude is safe above terrain
        
        Args:
            terrain: Terrain grid
            x: X coordinate
            y: Y coordinate
            altitude: Flight altitude (AMSL)
            safety_margin: Safety margin override
            
        Returns:
            Tuple of (is_safe, clearance)
        """
        margin = safety_margin or self.default_safety_margin
        terrain_elevation = terrain.get_elevation(x, y)
        clearance = altitude - terrain_elevation
        is_safe = clearance >= margin
        
        if not is_safe:
            logger.warning(
                f"Unsafe altitude at ({x}, {y}): "
                f"clearance={clearance:.1f}m < {margin}m"
            )
        
        return is_safe, clearance
    
    def get_minimum_safe_altitude(
        self,
        terrain: TerrainGrid,
        x: int,
        y: int,
        radius: int = 3
    ) -> float:
        """
        Calculate minimum safe altitude considering surrounding terrain
        
        Args:
            terrain: Terrain grid
            x: Center X coordinate
            y: Center Y coordinate
            radius: Search radius in grid cells
            
        Returns:
            Minimum safe altitude (AMSL)
        """
        max_elevation = 0.0
        
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    elevation = terrain.get_elevation(x + dx, y + dy)
                    max_elevation = max(max_elevation, elevation)
        
        return max_elevation + self.default_safety_margin
    
    def generate_terrain_profile(
        self,
        terrain: TerrainGrid,
        start: Tuple[int, int],
        end: Tuple[int, int],
        samples: int = 100
    ) -> List[TerrainPoint]:
        """
        Generate terrain elevation profile along a path
        
        Args:
            terrain: Terrain grid
            start: Start coordinates (x, y)
            end: End coordinates (x, y)
            samples: Number of sample points
            
        Returns:
            List of terrain points along the path
        """
        profile = []
        
        for i in range(samples):
            t = i / (samples - 1)
            x = int(start[0] + t * (end[0] - start[0]))
            y = int(start[1] + t * (end[1] - start[1]))
            
            # Convert grid to lat/lon (simplified)
            lat = terrain.origin_lat + (y / terrain.shape[0]) * 0.01
            lon = terrain.origin_lon + (x / terrain.shape[1]) * 0.01
            
            elevation = terrain.get_elevation(x, y)
            slope = terrain.get_slope(x, y)
            
            # Determine terrain type from slope
            if slope > 30:
                terrain_type = TerrainType.MOUNTAINOUS
            elif slope > 15:
                terrain_type = TerrainType.HILLY
            else:
                terrain_type = TerrainType.FLAT
            
            profile.append(TerrainPoint(
                latitude=lat,
                longitude=lon,
                elevation=elevation,
                terrain_type=terrain_type
            ))
        
        logger.debug(f"Generated terrain profile with {len(profile)} points")
        return profile
    
    def analyze_terrain_difficulty(
        self,
        terrain: TerrainGrid
    ) -> Dict[str, float]:
        """
        Analyze overall terrain difficulty
        
        Returns:
            Dictionary with difficulty metrics
        """
        slopes = []
        max_elevation = 0.0
        min_elevation = float('inf')
        
        for x in range(1, terrain.shape[0] - 1):
            for y in range(1, terrain.shape[1] - 1):
                slopes.append(terrain.get_slope(x, y))
                elevation = terrain.get_elevation(x, y)
                max_elevation = max(max_elevation, elevation)
                min_elevation = min(min_elevation, elevation)
        
        metrics = {
            'avg_slope': float(np.mean(slopes)),
            'max_slope': float(np.max(slopes)),
            'elevation_range': max_elevation - min_elevation,
            'max_elevation': max_elevation,
            'min_elevation': min_elevation,
            'difficulty_score': self._calculate_difficulty_score(
                float(np.mean(slopes)),
                float(np.max(slopes)),
                max_elevation - min_elevation
            )
        }
        
        logger.info(f"Terrain difficulty analysis: {metrics}")
        return metrics
    
    def _calculate_difficulty_score(
        self,
        avg_slope: float,
        max_slope: float,
        elevation_range: float
    ) -> float:
        """Calculate overall difficulty score (0-100)"""
        # Normalize factors
        slope_factor = min(avg_slope / self.max_slope_angle, 1.0)
        max_slope_factor = min(max_slope / 90.0, 1.0)
        elevation_factor = min(elevation_range / 1000.0, 1.0)
        
        # Weighted average
        score = (
            slope_factor * 30 +
            max_slope_factor * 40 +
            elevation_factor * 30
        )
        
        return score * 100
