import json

import docker
import paho.mqtt.client as paho
import pytest
import yaml


with open('epifi/epifi.yaml') as f:
    config = yaml.load(f)

# Insert stuff into the metadatabase
    # Insert data into mosquitto
    # Start docker-compose
    # Insert data into MongoDB


@pytest.fixture(scope="module")
def mqtt_client():
    client = paho.Client()
    client.username_pw_set(username='test_sensor', password='test')
    client.connect('localhost')
    client.loop_start()

    yield client

    client.disconnect()
    client.loop_stop()


# @pytest.fixture
# def add_mosquitto_users(scope="module"):
#     client = docker.from_env()

#     # Add password
#     mkpassword_command = f"mosquitto_passwd -b {password_file} {user['name']} {user['password']}"

#     container = client.containers.run(
#             image,
#             name=MOSQUITTO_CONTAINER_NAME,
#             detach=True,
#             volumes={persistent_storage: {'bind': '/mosquitto', 'mode': 'rw'}},
#             command=f'/bin/ash -c "cd /mosquitto/config && touch {password_file} && {mkpassword_command}"')




def test_add_sensor_data(mqtt_client, influx_client):
    measurement_time = 123
    data = {'sample_time': measurement_time,
            'temperature': 71,
            'humidity': 45,
            'pm_small': 1234,
            'pm_large': 82}

    message = mqtt_client.publish("epifi/v1/test_sensor_1", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Check InfluxDB for data
    data = influx_client.query(f"SELECT * FROM /.*/ WHERE time = {measurement_time}")
    assert len(data) > 0


def test_add_annotations(mqtt_client, influx_client):
    measurement_time = 123
    data = {'sample_time': measurement_time}

    message = mqtt_client.publish("epifi/v1/test_sensor_2", json.dumps(data), qos=1)
    message.wait_for_publish()

    # Check InfluxDB for data
    data = influx_client.query(f"SELECT * FROM /.*/ WHERE time = {measurement_time}")
    assert len(data) > 0


