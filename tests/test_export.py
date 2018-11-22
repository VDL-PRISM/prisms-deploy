import csv
from datetime import datetime, timedelta
import time

import requests


EXPORT_HOST = 'localhost:5001'


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
    user = config['export_user']['name']
    password = config['export_user']['password']
    return user, password


def test_no_auth():
    r = requests.get(f'http://{EXPORT_HOST}/')
    assert r.status_code == 401


def test_html(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/', auth=(user, password))

    assert r.status_code == 200
    assert len(r.content) > 1000


def test_generate_no_sensor_id(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate', auth=(user, password))

    assert r.status_code == 200
    response = r.json()
    assert 'error' in response


def test_generate_no_start(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': 5})

    assert r.status_code == 200
    response = r.json()
    assert 'error' in response


def test_generate_no_end(epifi_config):
    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': 5,
                             'start_date': 1})

    assert r.status_code == 200
    response = r.json()
    assert 'error' in response


def test_generate_unknown_sensor(epifi_config):
    sensor_id = 'sensor1'

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': 1,
                             'start_date': 1,
                             'end_date': 1})

    assert r.status_code == 200
    response = r.json()
    assert 'error' in response


def test_generate_bad_start_date(epifi_config):
    sensor_id = 'sensor1'

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': sensor_id,
                             'start_date': 'a',
                             'end_date': 1})

    assert r.status_code == 200
    response = r.json()
    assert 'error' in response


def test_generate_bad_end_date(epifi_config):
    sensor_id = 'sensor1'

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': sensor_id,
                             'start_date': 1,
                             'end_date': 'a'})

    assert r.status_code == 200
    response = r.json()
    assert 'error' in response


def test_generate_no_data(influx_client, epifi_config):
    sensor_id = 'sensor1'
    now = datetime.utcnow()
    num_measurements = 5
    add_data(influx_client, sensor_id, now, num_measurements)

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': sensor_id,
                             'start_date': now - timedelta(days=10),
                             'end_date': now - timedelta(days=5)})

    assert r.status_code == 200
    response = r.json()
    assert 'error' in response


def test_generate_csv(influx_client, epifi_config):
    sensor_id = 'sensor1'
    now = datetime.utcnow()
    num_measurements = 5
    add_data(influx_client, sensor_id, now, num_measurements)

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': sensor_id,
                             'start_date': now - timedelta(hours=6),
                             'end_date': now})

    assert r.status_code == 200

    decoded_content = r.content.decode('utf-8')
    data = csv.reader(decoded_content.splitlines(), delimiter=',')
    data = list(data)
    assert len(data) == num_measurements + 1  # For a header


def test_generate_json(influx_client, epifi_config):
    sensor_id = 'sensor1'
    now = datetime.utcnow()
    num_measurements = 5
    add_data(influx_client, sensor_id, now, num_measurements)

    user, password = get_user_and_password(epifi_config)
    r = requests.get(f'http://{EXPORT_HOST}/generate',
                     auth=(user, password),
                     params={'sensor_id': sensor_id,
                             'start_date': now - timedelta(hours=6),
                             'end_date': now,
                             'data_type': 'json'})

    assert r.status_code == 200
    data = r.json()

    assert len(data) == 3
    assert 'columns' in data
    assert 'data' in data
    assert 'index' in data

    assert len(data['data']) == num_measurements
