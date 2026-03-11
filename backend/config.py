"""
SkyMaster配置文件
"""

from pydantic import BaseSettings
from typing import List, Optional
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用信息
    APP_NAME: str = "SkyMaster Drone Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # API配置
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"
    
    # CORS配置
    CORS_ORIGINS: List[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: List[str] = ["*"]
    CORS_ALLOW_HEADERS: List[str] = ["*"]
    
    # 数据库配置
    DATABASE_URL: str = "postgresql://skymaster:password@localhost:5432/skymaster"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    
    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None
    
    # TimescaleDB配置
    TIMESCALEDB_ENABLED: bool = True
    
    # MAVLink配置
    MAVLINK_DEFAULT_BAUD_RATE: int = 57600
    MAVLINK_TIMEOUT: float = 5.0
    MAVLINK_HEARTBEAT_INTERVAL: float = 1.0
    
    # 设备管理配置
    DEVICE_MAX_CONNECTIONS: int = 100
    DEVICE_OFFLINE_TIMEOUT: float = 10.0
    
    # WebSocket配置
    WS_HEARTBEAT_INTERVAL: float = 30.0
    WS_MAX_CONNECTIONS: int = 1000
    
    # 视频流配置
    VIDEO_STREAM_ENABLED: bool = True
    VIDEO_STREAM_RTSP_PORT: int = 8554
    VIDEO_STREAM_WEBRTC_PORT: int = 8080
    
    # 安全配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ALGORITHM: str = "HS256"
    
    # JWT配置
    JWT_SECRET_KEY: str = "your-jwt-secret-key"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # 地理围栏配置
    GEOFENCE_ENABLED: bool = True
    GEOFENCE_DEFAULT_RADIUS: float = 1000.0  # 米
    
    # 飞行限制
    MAX_FLIGHT_ALTITUDE: float = 120.0  # 米
    MAX_FLIGHT_DISTANCE: float = 5000.0  # 米
    MAX_FLIGHT_SPEED: float = 15.0  # m/s
    
    # 电池保护
    BATTERY_LOW_THRESHOLD: int = 20  # %
    BATTERY_CRITICAL_THRESHOLD: int = 10  # %
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/skymaster.log"
    LOG_MAX_SIZE: int = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT: int = 5
    
    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    
    # 集群配置
    SWARM_MAX_SIZE: int = 20
    SWARM_MIN_SEPARATION: float = 5.0  # 米
    SWARM_SYNC_TOLERANCE: float = 2.0  # 米
    
    # 任务配置
    MISSION_MAX_WAYPOINTS: int = 1000
    MISSION_AUTO_SAVE: bool = True
    
    # Cesium配置
    CESIUM_ION_TOKEN: str = "your-cesium-ion-token"
    
    # 地图配置
    MAP_DEFAULT_LATITUDE: float = 39.9042
    MAP_DEFAULT_LONGITUDE: float = 116.4074
    MAP_DEFAULT_ZOOM: int = 15
    
    # 文件存储
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    
    # 第三方服务
    DJI_SDK_APP_ID: Optional[str] = None
    DJI_SDK_APP_KEY: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


class DevelopmentSettings(Settings):
    """开发环境配置"""
    DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"


class ProductionSettings(Settings):
    """生产环境配置"""
    DEBUG: bool = False
    LOG_LEVEL: str = "WARNING"
    
    # 生产环境必须设置这些值
    SECRET_KEY: str
    JWT_SECRET_KEY: str
    DATABASE_URL: str
    REDIS_URL: str


class TestingSettings(Settings):
    """测试环境配置"""
    DEBUG: bool = True
    TESTING: bool = True
    DATABASE_URL: str = "postgresql://skymaster:password@localhost:5432/skymaster_test"


@lru_cache()
def get_settings() -> Settings:
    """获取配置实例"""
    import os
    
    env = os.getenv("ENVIRONMENT", "development")
    
    if env == "production":
        return ProductionSettings()
    elif env == "testing":
        return TestingSettings()
    else:
        return DevelopmentSettings()


# 全局配置实例
settings = get_settings()
