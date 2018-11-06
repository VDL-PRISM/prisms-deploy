from influxdb import InfluxDBClient
import pytest
import yaml


@pytest.fixture
def influx_client():
    with open('epifi/epifi.yaml') as f:
        config = yaml.load(f)

    client = InfluxDBClient(username=config['influxdb_admin']['name'],
                            password=config['influxdb_admin']['password'],
                            database='epifi')
    return client


@pytest.fixture
def docker_compose():
    # Move certificate files
    # Start docker compose
    yield
    # Stop docker compose
    # Delete certificate files
