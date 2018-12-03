from datetime import datetime
import json
import os
import tempfile
import time

import arrow
import docker
import paho.mqtt.client as paho
from persistent_queue import PersistentQueue
from pymongo import MongoClient
import pytest
import yaml

CONTAINER = 'epifi_subscriber'


def check_influx(client, measurement, time):
    time_str = arrow.get(time)
    query = f"SELECT * FROM {measurement} WHERE time = '{time_str}'"
    data = client.query(query)
    assert len(data) == 1


def get_queues_sizes(container, data_path='/app/data'):
    client = docker.from_env()

    # Create temporary directory
    with tempfile.TemporaryDirectory(dir='.') as directory:
        directory = os.path.abspath(directory)

        # Copy queues
        client.containers.run("ubuntu", f"cp -r {data_path} /temp/",
                              remove=True,
                              user=os.environ['USER'],
                              volumes_from=[container],
                              volumes={directory: {'bind': '/temp'}})

        good = PersistentQueue(os.path.join(directory, 'data/data.queue'))
        bad = PersistentQueue(os.path.join(directory, 'data/bad-data.queue'))
        return len(good), len(bad)


def test_not_json(mqtt_client):
    good_before, bad_before = get_queues_sizes(CONTAINER)

    data = 'this is not json'

    message = mqtt_client.publish("epifi/v1/test_sensor_1", data, qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    good_after, bad_after = get_queues_sizes(CONTAINER)
    assert good_before == good_after
    assert bad_before == bad_after - 1


def test_missing_sample_time(mqtt_client):
    good_before, bad_before = get_queues_sizes(CONTAINER)

    data = {'temperature': [71, 'F'],
            'humidity': [45, '%'],
            'pm_small': [1234, 'pm'],
            'pm_large': [82, 'pm']}

    message = mqtt_client.publish("epifi/v1/test_sensor_1", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    good_after, bad_after = get_queues_sizes(CONTAINER)
    assert good_before == good_after
    assert bad_before == bad_after - 1


def test_add_sensor_data(mqtt_client, influx_client, mongodb_deployments):
    measurement_time = int(time.time())

    data = {'sample_time': [measurement_time, 's'],
            'temperature': [71, 'F'],
            'humidity': [45, '%'],
            'pm_small': [1234, 'pm'],
            'pm_large': [82, 'pm']}

    message = mqtt_client.publish("epifi/v1/test_sensor_1", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    # Check InfluxDB for data
    for key in data:
        check_influx(influx_client, key, measurement_time)



def test_add_annotations(mqtt_client, influx_client, mongodb_deployments):
    measurement_time = int(time.time())

    data = {'sample_time': [measurement_time, 's'],
            'annotation': ['this is a test', 'speaking']}

    message = mqtt_client.publish("epifi/v1/test_sensor_2", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    # Check InfluxDB for data
    for key in data:
        check_influx(influx_client, key, measurement_time)


