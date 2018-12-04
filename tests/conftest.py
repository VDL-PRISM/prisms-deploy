import subprocess

from influxdb import InfluxDBClient
import paho.mqtt.client as paho
from pymongo import MongoClient
import pytest
import yaml


@pytest.fixture
def influx_client():
    with open('epifi/epifi.yaml') as f:
        config = yaml.load(f)

    database = 'epifi'
    client = InfluxDBClient(username=config['influxdb_admin']['name'],
                            password=config['influxdb_admin']['password'],
                            database=database)

    # Delete all data in database
    measurements = client.get_list_measurements()
    for m in measurements:
        client.drop_measurement(m['name'])

    yield client

    # Delete all data in database
    measurements = client.get_list_measurements()
    for m in measurements:
        client.drop_measurement(m['name'])


@pytest.fixture
def mongo_client():
    with open('epifi/epifi.yaml') as f:
        config = yaml.load(f)

    database = config['mongodb_database']
    collection = 'deployments'
    mongodb_url = 'mongodb://{user}:{password}@{host}:{port}/admin'.format(
        user=config['mongo_admin']['name'],
        password=config['mongo_admin']['password'],
        host='localhost',
        port=27017,
        database=database)
    mongo_client = MongoClient(mongodb_url)
    deployments = mongo_client[database][collection]

    deployments.delete_many({})
    yield deployments
    deployments.delete_many({})


# @pytest.fixture
# def docker_compose(scope="module"):
#     cmd = 'docker-compose -f epifi/docker-compose.yaml -f tests/docker-compose.test.yaml up'

#     print("Starting docker compose")
#     p = subprocess.Popen(cmd, shell=True)
#     print(p)
#     yield
#     # Stop docker compose
#     # Delete certificate files


@pytest.fixture
def epifi_config(scope="module"):
    with open('epifi/epifi.yaml') as f:
        yield yaml.load(f)


@pytest.fixture(scope="module")
def mqtt_client():
    client = paho.Client()
    client.username_pw_set(username='test_sensor', password='test')
    client.connect('localhost')
    client.loop_start()

    yield client

    client.disconnect()
    client.loop_stop()


@pytest.fixture
def mongodb_deployments(scope="module"):
    with open('epifi/epifi.yaml') as f:
        config = yaml.load(f)

    database = config['mongodb_database']
    collection = 'deployments'
    mongodb_url = 'mongodb://{user}:{password}@{host}:{port}/admin'.format(
        user=config['mongo_admin']['name'],
        password=config['mongo_admin']['password'],
        host='localhost',
        port=27017,
        database=database)
    mongo_client = MongoClient(mongodb_url)
    deployments = mongo_client[database][collection]

    deployment_id = deployments.insert_one({
        "name": "Deployment 1",
        "active": True,
        "sensors": {
            "test_sensor_1": {
                "name": "Test Sensor",
                "important_measurement": "pm_small"
            },
            "test_sensor_2": {
                "name": "Person 1",
                "important_measurement": "annotation"
            }
        }
    })

    yield deployments

    deployments.delete_many({})
