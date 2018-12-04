from datetime import datetime
import json
import os
import subprocess
import tempfile
import time

import arrow
import docker
import paho.mqtt.client as paho
from persistent_queue import PersistentQueue
import pytest
import yaml

CONTAINER = 'epifi_ha_subscriber'

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
                              volumes_from=[container],
                              volumes={directory: {'bind': '/temp'}})

        subprocess.call(['sudo', 'chown', '-R', 'travis:travis', directory])

        good = PersistentQueue(os.path.join(directory, 'data/data.queue'))
        bad = PersistentQueue(os.path.join(directory, 'data/bad-data.queue'))
        return len(good), len(bad)


def test_not_json(mqtt_client):
    good_before, bad_before = get_queues_sizes(CONTAINER)

    data = 'this is not json'

    message = mqtt_client.publish("epifi/ha/v1/deployment_1", data, qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    good_after, bad_after = get_queues_sizes(CONTAINER)
    assert good_before == good_after
    assert bad_before + 1 == bad_after


def test_wrong_format(mqtt_client):
    good_before, bad_before = get_queues_sizes(CONTAINER)
    measurement_time = int(time.time())

    data = {'sample_time': [measurement_time, 's'],
            'temperature': [71, 'F'],
            'humidity': [45, '%'],
            'pm_small': [1234, 'pm'],
            'pm_large': [82, 'pm']}

    message = mqtt_client.publish("epifi/ha/v1/deployment_1", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    good_after, bad_after = get_queues_sizes(CONTAINER)
    assert good_before == good_after
    assert bad_before == bad_after - 1


def test_missing_sample_time(mqtt_client):
    good_before, bad_before = get_queues_sizes(CONTAINER)
    measurement_time = int(time.time())

    data = {'event_data': {'old_state': {},
                           'new_state': {'entity_id': 'sensor.sensor1_temperature',
                                         'state': 80,
                                         'attributes': {}}}}

    message = mqtt_client.publish("epifi/ha/v1/deployment_1", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    good_after, bad_after = get_queues_sizes(CONTAINER)
    assert good_before == good_after
    assert bad_before == bad_after - 1


def test_add_sensor_data(mqtt_client, influx_client):
    good_before, bad_before = get_queues_sizes(CONTAINER)
    measurement_time = int(time.time())
    measurement = 'temperature'

    data = {'event_data': {'old_state': {},
                           'new_state': {'entity_id': f'sensor.sensor1_{measurement}',
                                         'state': 80,
                                         'attributes': {'sample_time': measurement_time}}}}

    message = mqtt_client.publish("epifi/ha/v1/deployment_1", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    good_after, bad_after = get_queues_sizes(CONTAINER)
    assert good_before == good_after
    assert bad_before == bad_after

    # Check InfluxDB for data
    check_influx(influx_client, measurement, measurement_time)


def test_add_annotation(mqtt_client, influx_client):
    good_before, bad_before = get_queues_sizes(CONTAINER)
    measurement_time = int(time.time())
    measurement = 'annotation'

    data = {'event_data': {'old_state': {},
                           'new_state': {'entity_id': f'sensor.sensor1_{measurement}',
                                         'state': 'test annotation',
                                         'attributes': {'sample_time': measurement_time}}}}

    message = mqtt_client.publish("epifi/ha/v1/deployment_1", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Give time for data to get through system
    time.sleep(.2)

    good_after, bad_after = get_queues_sizes(CONTAINER)
    assert good_before == good_after
    assert bad_before == bad_after

    # Check InfluxDB for data
    check_influx(influx_client, measurement, measurement_time)

