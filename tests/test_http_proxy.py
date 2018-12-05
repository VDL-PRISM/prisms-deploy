import json
import time

import arrow
import requests


HOST = 'localhost:5003'


def check_influx(client, measurement, time):
    time_str = arrow.get(time / 1e6)
    query = f"SELECT * FROM {measurement} WHERE time = '{time_str}'"
    data = client.query(query)
    assert len(data) == 1

    data = list(data.get_points(measurement))[0]

    assert 'deployment_active' in data
    assert 'deployment_id' in data
    assert 'deployment_name' in data
    assert 'sensor_id' in data
    assert 'sensor_important_measurement' in data
    assert 'sensor_name' in data
    assert 'value' in data or 'state' in data


def get_user_and_password(config):
    user = config['http_proxy_user']['name']
    password = config['http_proxy_user']['password']
    return user, password


def test_no_auth():
    r = requests.post(f'http://{HOST}/data')
    assert r.status_code == 401


def test_no_data(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.post(f'http://{HOST}/data', auth=(user, password))

    assert r.status_code == 400
    assert 'error' in r.json()


def test_not_json(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      data='this is a test')

    assert r.status_code == 400
    assert 'error' in r.json()


def test_wrong_format(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json={'wrong': 'format'})

    assert r.status_code == 400
    assert 'error' in r.json()


def test_missing_sample_time(epifi_config):
    user, password = get_user_and_password(epifi_config)
    data = {
        "sensor_id": "sensor_1",
        "data": {
            "temperature": 71,
            "humidity": 45,
            "pm_small": 1234,
            "pm_large": 82
        }
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    assert r.status_code == 400
    assert 'error' in r.json()


def test_missing_sensor_id(epifi_config):
    user, password = get_user_and_password(epifi_config)
    measurement_time = int(time.time() * 1e6)

    data = {
        "sample_time": measurement_time,
        "data": {
            "temperature": 71,
            "humidity": 45,
            "pm_small": 1234,
            "pm_large": 82
        }
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    assert r.status_code == 400
    assert 'error' in r.json()


def test_missing_data(epifi_config):
    user, password = get_user_and_password(epifi_config)
    measurement_time = int(time.time() * 1e6)

    data = {
        "sample_time": measurement_time,
        "sensor_id": "sensor_1",
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    assert r.status_code == 400
    assert 'error' in r.json()


def test_wrong_time_format(epifi_config):
    user, password = get_user_and_password(epifi_config)

    data = {
        "sample_time": 'time',
        "sensor_id": "sensor_1",
        "data": {
            "temperature": 71,
            "humidity": 45,
            "pm_small": 1234,
            "pm_large": 82
        }
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    assert r.status_code == 400
    assert 'error' in r.json()

    data = {
        "sample_time": -1000,
        "sensor_id": "sensor_1",
        "data": {
            "temperature": 71,
            "humidity": 45,
            "pm_small": 1234,
            "pm_large": 82
        }
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    assert r.status_code == 400
    assert 'error' in r.json()


def test_bad_sensor_id(epifi_config):
    user, password = get_user_and_password(epifi_config)
    measurement_time = int(time.time() * 1e6)

    data = {
        "sample_time": measurement_time,
        "sensor_id": "sensor 1",  # Contains an invalid character
        "data": {
            "temperature": 71,
            "humidity": 45,
            "pm_small": 1234,
            "pm_large": 82
        }
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    assert r.status_code == 400
    assert 'error' in r.json()

    data = {
        "sample_time": measurement_time,
        "sensor_id": "🦖",  # Contains unicode
        "data": {
            "temperature": 71,
            "humidity": 45,
            "pm_small": 1234,
            "pm_large": 82
        }
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    assert r.status_code == 400
    assert 'error' in r.json()


def test_add_sensor_data(epifi_config, influx_client, mongodb_deployments):
    user, password = get_user_and_password(epifi_config)
    measurement_time = int(time.time() * 1e6)

    data = {
        "sample_time": measurement_time,
        "sensor_id": "test_sensor_1",
        "data": {
            "temperature": 71,
            "humidity": 45,
            "pm_small": 1234,
            "pm_large": 82,
            "annotation": "something happened"
        },
        "metadata": {
            "firmware": "v1.0"
        }
    }

    r = requests.post(f'http://{HOST}/data', auth=(user, password),
                      json=data)

    time.sleep(.2)

    # Check InfluxDB for data
    for key in data['data']:
        check_influx(influx_client, key, measurement_time)
