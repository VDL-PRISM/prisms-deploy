from datetime import datetime, timedelta
import time

import requests

HOST = 'localhost:5002'


def create_point(time, measurement, value, sensor_id, deployment_id):
    return {
        "time": time,
        "measurement": measurement,
        "tags": {
            "sensor_id": sensor_id,
            "deployment_id": deployment_id
        },
        "fields": {
            "value": value
        }
    }


def add_data(influx_client, sensor_id, measurement_time, num):
    deployment_id = 'deployment1'
    points = []

    for i in range(num):
        measurement_time -= timedelta(minutes=1)
        points.append(create_point(measurement_time, 'temperature', 80, sensor_id, deployment_id))
        points.append(create_point(measurement_time, 'humidity', 42, sensor_id, deployment_id))
        points.append(create_point(measurement_time, 'pm_small', 1821, sensor_id, deployment_id))
        points.append(create_point(measurement_time, 'pm_large', 291, sensor_id, deployment_id))

        if len(points) % 1000 == 0:
            influx_client.write_points(points)
            points = []

    influx_client.write_points(points)


def get_user_and_password(config):
    user = config['status_user']['name']
    password = config['status_user']['password']
    return user, password


def test_no_auth():
    r = requests.get(f'http://{HOST}/')
    assert r.status_code == 401


def test_html_no_data(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{HOST}/', auth=(user, password))

    assert r.status_code == 200


def test_update_no_data(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{HOST}/update', auth=(user, password))

    assert r.status_code == 200

    data = r.json()
    assert 'data' in data
    assert 'now' in data
    assert len(data['data']) == 0


def test_missing_sensors(epifi_config, mongo_client):
    deployment_id = 'Deployment 1'
    now = datetime.utcnow()
    num_measurements = 1

    mongo_client.insert_one({
        "name": deployment_id,
        "active": True,
    })

    time.sleep(2)

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{HOST}/update', auth=(user, password))

    assert r.status_code == 200

    data = r.json()
    assert 'data' in data
    assert 'now' in data
    assert len(data['data']) != 0

    assert deployment_id in data['data']
    assert len(data['data'][deployment_id]) == 0


def test_missing_important_measurement(influx_client, epifi_config, mongo_client):
    sensor_id = 'test_sensor_1'
    deployment_id = 'Deployment 1'
    now = datetime.utcnow()
    num_measurements = 1
    add_data(influx_client, sensor_id, now, num_measurements)

    mongo_client.insert_one({
        "name": deployment_id,
        "active": True,
        "sensors": {
            sensor_id: {
                "name": "Test Sensor",
            }
        }
    })

    time.sleep(2)

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{HOST}/update', auth=(user, password))

    assert r.status_code == 200

    data = r.json()
    assert 'data' in data
    assert 'now' in data
    assert len(data['data']) != 0

    assert deployment_id in data['data']
    assert sensor_id in data['data'][deployment_id]
    assert data['data'][deployment_id][sensor_id] is None


def test_update(influx_client, epifi_config, mongo_client):
    sensor_id = 'test_sensor_1'
    deployment_id = 'Deployment 1'
    now = datetime.utcnow()
    num_measurements = 1
    add_data(influx_client, sensor_id, now, num_measurements)

    mongo_client.insert_one({
        "name": deployment_id,
        "active": True,
        "sensors": {
            sensor_id: {
                "name": "Test Sensor",
                "important_measurement": "pm_small"
            }
        }
    })

    time.sleep(2)

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{HOST}/update', auth=(user, password))

    assert r.status_code == 200

    data = r.json()
    assert 'data' in data
    assert 'now' in data
    assert len(data['data']) != 0

    assert deployment_id in data['data']
    assert sensor_id in data['data'][deployment_id]
    assert data['data'][deployment_id][sensor_id] is not None
