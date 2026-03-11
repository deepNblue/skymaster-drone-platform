"""Test MAVLink connector"""
import pytest
from core.mavlink.connector import MAVLinkConnector, PX4Connector

def test_connector_creation():
    """Test connector instantiation"""
    connector = PX4Connector("drone_1", "tcp:127.0.0.1:5760")
    assert connector.device_id == "drone_1"
    assert connector.connection_string == "tcp:127.0.0.1:5760"

# Add more tests...
