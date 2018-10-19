import json
import os
import secrets
import shutil
import string
import sys
import tempfile
import threading
import time

import click
import docker
import enlighten
import influxdb
from jinja2 import Environment, FileSystemLoader
import yaml


MONGODB_CONTAINER_NAME = 'epifi-mongodb'
INFLUX_CONTAINER_NAME = 'epifi-influxdb'
GRAFANA_CONTAINER_NAME = 'epifi-grafana'
MOSQUITTO_CONTAINER_NAME = 'epifi-mosquitto'
CONFIG_FILE_NAME = 'epifi.yaml'

def main():

    config = {}
    if os.path.isfile(CONFIG_FILE_NAME):
        # Load configuration file
        with open(CONFIG_FILE_NAME) as f:
            config = yaml.load(f) or {}

    click.echo("Welcome to the EpiFi architecture setup!\n")
    if not config.get('subdomains'):
        click.echo("This setup script assumes that you own a domain name and that"
                    " each service will run as a subdomain. If this is not the"
                    " case, then you should stop.")
        if not click.confirm("Would you like to continue?", default=True):
            click.echo("Bye!")
            return

    click.echo("\n\nGreat! Let's start with a couple of questions.")
    if config.get('use_lets_encrypt', True):
        config['use_lets_encrypt'] = click.confirm(
            "Would you like to use Let's Encrypt to generate certificates?",
            default=False)

    if config['use_lets_encrypt']:
        config['lets_encrypt_email'] = config.get('lets_encrypt_email') or click.prompt("What email address do you want to use?")
    else:
        click.echo("\n\nThat's fine. You will have to get your own SSL "
                    "certificates. Once you have done that, put the keys in "
                    "the 'certs' folder.")

    config['hostname'] = config.get('hostname') or click.prompt("What is the base hostname?")
    click.echo("\n\n")
    config['influxdb_hostname'] = config.get('influxdb_hostname') or get_hostname('the database', 'db', config['hostname'])
    config['mqtt_hostname'] = config.get('mqtt_hostname') or get_hostname('the MQTT broker', 'mqtt', config['hostname'])
    config['grafana_hostname'] = config.get('grafana_hostname') or get_hostname('Grafana', 'grafana', config['hostname'])
    config['mongodb_hostname'] = config.get('mongodb_hostname') or get_hostname('the metadata store', 'meta', config['hostname'])
    config['export_hostname'] = config.get('export_hostname') or get_hostname('the export tool', 'export', config['hostname'])
    config['status_hostname'] = config.get('status_hostname') or get_hostname('the status dashboard', 'status', config['hostname'])

    config['export_user'] = create_user('epifi')

    client = docker.from_env()

    mongodb_setup(client, config)
    influxdb_setup(client, config)
    grafana_setup(client, config, INFLUX_CONTAINER_NAME)
    mosquitto_setup(client, config)

    # Fill in passwords for .env file
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template('env.template')

    print(config)

    # print(template.render(**config))


def get_hostname(name, default_value, base_host_name):
    done = False
    while not done:
        subdomain = click.prompt(f"What do you want the subdomain of {name}?",
                                 default=default_value)

        done = click.confirm(f"Is {subdomain}.{base_host_name} correct?", default=True)

    subdomain = default_value

    return f"{subdomain}.{base_host_name}"


def mosquitto_setup(client, config, persistent_storage='./mosquitto-storage',
                    image='eclipse-mosquitto:latest',
                    root_topic='epifi'):
    print("\n\nSetting up Mosquitto")
    persistent_storage = os.path.abspath(persistent_storage)
    if not handle_existing_container(client, MOSQUITTO_CONTAINER_NAME, persistent_storage):
        return

    config['mqtt_subscriber_topic'] = f'{root_topic}/v1/#'
    config['mqtt_subscriber'] = create_user('subscriber', topic=config['mqtt_subscriber_topic'])
    config['mqtt_ha_subscriber_topic'] = f'{root_topic}/ha/v1/#'
    config['mqtt_ha_subscriber'] = create_user('ha_subscriber', topic=config['mqtt_ha_subscriber_topic'])
    users = [config['mqtt_subscriber'], config['mqtt_ha_subscriber']]

    config_path = os.path.join(persistent_storage, 'config')
    # Make config directory in storage folder
    os.makedirs(os.path.join(config_path, 'certs'))

    # Copy over config file
    shutil.copy('templates/mosquitto.conf', config_path)
    shutil.copy('templates/ca.pem', os.path.join(config_path, 'certs', 'ca.pem'))

    # Create acl_file
    with open(os.path.join(config_path, 'acl'), 'w') as f:
        lines = [f"pattern write {root_topic}/v1/%u/#",
                 f"pattern write {root_topic}/ha_v1/%u/#",
                 ""]

        for user in users:
            lines.extend([f"user {user['name']}",
                          f"topic read {user['topic']}",
                          ""])

        f.write('\n'.join(lines))

    print(f"Pulling {image} (could take awhile)...")
    output = docker.APIClient().pull(image, stream=True, decode=True)
    print_status(output)

    # Create password file
    password_file = 'passwords'
    mkpassword_command = [f"mosquitto_passwd -b {password_file} {user['name']} {user['password']}"
                          for user in users]
    mkpassword_command = ' && '.join(mkpassword_command)

    container = client.containers.run(
            image,
            name=MOSQUITTO_CONTAINER_NAME,
            detach=True,
            volumes={persistent_storage: {'bind': '/mosquitto', 'mode': 'rw'}},
            command=f'/bin/ash -c "cd /mosquitto/config && touch {password_file} && {mkpassword_command}"')

    print(f"Waiting for {MOSQUITTO_CONTAINER_NAME} to initialize...")
    wait_for_done(container)

    print(f"Stopping {MOSQUITTO_CONTAINER_NAME}...")
    container.stop()
    print(f"Removing {MOSQUITTO_CONTAINER_NAME}...")
    container.remove()


def grafana_setup(client, config, influxdb_cointainer_name,
                  persistent_storage='./grafana-storage',
                  database_name='epifi', image='grafana/grafana:latest'):
    print("\n\nSetting up Grafana")
    persistent_storage = os.path.abspath(persistent_storage)
    if not handle_existing_container(client, GRAFANA_CONTAINER_NAME, persistent_storage):
        return

    if 'influxdb_grafana' not in config:
        click.echo("Looks like InfluxDB was set up previously. "
                   "Please enter the password for the 'grafana' user in InfluxDB.")
        config['influxdb_grafana'] = {'name': 'grafana',
                                      'password': click.prompt('Password', hide_input=True),
                                      'role': 'read'}
    influxdb_user = config['influxdb_grafana']

    config['grafana_admin'] = create_user('admin')

    print(f"Pulling {image} (could take awhile)...")
    output = docker.APIClient().pull(image, stream=True, decode=True)
    print_status(output)

    with tempfile.NamedTemporaryFile(dir='.') as f:
        # Set up configuration file
        datasources = {'apiVersion': 1,
                       'datasources': [{'name': 'epifi',
                                        'type': 'influxdb',
                                        'access': 'proxy',
                                        'url': f'http://{influxdb_cointainer_name}:8086',
                                        'database': database_name,
                                        'isDefault': True,
                                        'user': influxdb_user['name'],
                                        'password': influxdb_user['password'],
                                        'version': 1,
                                        'editable': True}]}
        f.write(yaml.dump(datasources).encode())
        f.flush()

        container = client.containers.run(
            image,
            name=GRAFANA_CONTAINER_NAME,
            detach=True,
            ports={'3000/tcp': 3000},
            environment={'GF_SECURITY_ADMIN_PASSWORD': config['grafana_admin']['password']},
            volumes={f.name: {'bind': '/etc/grafana/provisioning/datasources/datasource.yaml',
                              'mode': 'ro'},
                     persistent_storage: {'bind': '/var/lib/grafana', 'mode': 'rw'}})

        print(f"Waiting for {GRAFANA_CONTAINER_NAME} to initialize...")
        wait_for_done(container)

        print(f"Stopping {GRAFANA_CONTAINER_NAME}...")
        container.stop()
        print(f"Removing {GRAFANA_CONTAINER_NAME}...")
        container.remove()


def influxdb_setup(client, config, persistent_storage='./influxdb-storage',
                   database_name='epifi', image='influxdb:1.6'):
    print("\n\nSetting up InfluxDB")
    persistent_storage = os.path.abspath(persistent_storage)
    if not handle_existing_container(client, INFLUX_CONTAINER_NAME, persistent_storage):
        return

    config['influxdb_admin'] = create_user('admin', role='admin')
    config['influxdb_status'] = create_user('status', role='read')
    config['influxdb_export'] = create_user('export', role='read')
    config['influxdb_grafana'] = create_user('grafana', role='read')
    config['influxdb_mqtt_uploader'] = create_user('uploader', role='write')
    config['influxdb_mqtt_ha_uploader'] = create_user('ha_uploader', role='write')
    users = [config['influxdb_admin'],
             config['influxdb_status'],
             config['influxdb_export'],
             config['influxdb_grafana'],
             config['influxdb_mqtt_uploader'],
             config['influxdb_mqtt_ha_uploader']]

    print(f"Pulling {image} (could take awhile)...")
    output = docker.APIClient().pull(image, stream=True, decode=True)
    print_status(output)

    container = client.containers.run(
        image,
        name=INFLUX_CONTAINER_NAME,
        detach=True,
        ports={'8086/tcp': 8086},
        volumes={persistent_storage: {'bind': '/var/lib/influxdb', 'mode': 'rw'}})

    print(f"Waiting for {INFLUX_CONTAINER_NAME} to initialize...")
    wait_for_done(container)

    influx_client = influxdb.InfluxDBClient()

    influx_client.create_database(database_name)

    for user in users:
        influx_client.create_user(user['name'], user['password'], user['role'] == 'admin')
        if user['role'] != 'admin':
            influx_client.grant_privilege(user['role'], database_name, user['name'])

    wait_for_done(container)
    print(f"Stopping {INFLUX_CONTAINER_NAME}...")
    container.stop()
    print(f"Removing {INFLUX_CONTAINER_NAME}...")
    container.remove()


def mongodb_setup(client, config, persistent_storage='./mongodb-storage',
                  database_name='epifi', collection_name='deployments',
                  image='mongo:4.0'):
    print("\n\nSetting up MongoDB")
    persistent_storage = os.path.abspath(persistent_storage)
    if not handle_existing_container(client, MONGODB_CONTAINER_NAME, persistent_storage):
        return

    config['mongo_mqtt_reader'] = create_user('mqtt_reader', role='read')
    config['mongo_status_reader'] = create_user('status_reader', role='read')
    config['mongo_admin'] = create_user('admin', role='admin')
    admin_user = config['mongo_admin']
    other_users = [config['mongo_mqtt_reader'], config['mongo_status_reader']]

    print(f"Pulling {image} (could take awhile)...")
    output = docker.APIClient().pull(image, stream=True, decode=True)
    print_status(output)

    # Set up configuration files
    with tempfile.NamedTemporaryFile(dir='.') as f:
        f.write(f"db.createCollection('{collection_name}')\n".encode())
        for user in other_users:
            name = user['name']
            password = user['password']
            role = user['role']
            f.write(f"db.createUser({{user:'{name}', pwd:'{password}', roles:[{{role:'{role}', db:'{database_name}'}}]}});\n".encode())
        f.flush()

        print(f"Starting {MONGODB_CONTAINER_NAME}...")
        container = client.containers.run(
            image,
            name=MONGODB_CONTAINER_NAME,
            command='--smallfiles',
            detach=True,
            environment={'MONGO_DATA_DIR': '/data/db',
                         'MONGO_INITDB_ROOT_USERNAME': admin_user['name'],
                         'MONGO_INITDB_ROOT_PASSWORD': admin_user['password'],
                         'MONGO_INITDB_DATABASE': database_name},
            volumes={f.name: {'bind': '/docker-entrypoint-initdb.d/1-setup.js',
                              'mode': 'ro'},
                     persistent_storage: {'bind': '/data/db', 'mode': 'rw'}})

        print(f"Waiting for {MONGODB_CONTAINER_NAME} to initialize...")
        wait_for_done(container)
        print(f"Stopping {MONGODB_CONTAINER_NAME}...")
        container.stop()
        print(f"Removing {MONGODB_CONTAINER_NAME}...")
        container.remove()


def create_user(name, **kwargs):
    return {'name': name,
            'password': generate_password(),
            **kwargs}


def print_status(logs):
    manager = enlighten.get_manager()

    pbars = {}
    for line in logs:
        if line['status'] == 'Pulling fs layer' and line['id'] not in pbars:
            pbar = manager.counter(
                                   desc=f"Waiting {line['id']}",
                                   unit='B')
            pbars[line['id']] = pbar

        elif line['status'] == 'Downloading' and line['id'] in pbars:
            progress = line['progressDetail']
            pbar = pbars[line['id']]

            pbar.total = progress['total']
            pbar.desc = f"Downloading {line['id']}"
            pbar.update(progress['current'] - pbar.count)

        elif line['status'] == 'Download complete' and line['id'] in pbars:
            pbar = pbars[line['id']]

            pbar.desc = f"Downloaded {line['id']}"
            pbar.update(pbar.total - pbar.count)

        elif line['status'] == 'Extracting' and line['id'] in pbars:
            progress = line['progressDetail']
            pbar = pbars[line['id']]

            if pbar.total == pbar.count:
                pbar.count = 0

            pbar.update(progress['current'] - pbar.count)
            pbar.desc = f"Extracting {line['id']}"

        elif line['status'] == 'Pull complete' and line['id'] in pbars:
            pbar = pbars[line['id']]
            pbar.desc = f"Pull complete {line['id']}"
            pbar.update(pbar.total - pbar.count)

    manager.stop()
    print()


def wait_for_done(container, wait_time=5, print_logs=False):
    check_time = 1
    empty_logs = 0
    old_now = 1

    while True:
        time.sleep(check_time)
        now = int(time.time())
        logs = container.logs(since=old_now)
        old_now = now

        if len(logs) == 0:
            empty_logs += 1
        else:
            empty_logs = 0
            if print_logs:
                # TODO: It is possible that log is printed twice
                print(logs.decode(), end='')

        if empty_logs == wait_time:
            break


def handle_existing_container(client, container_name, persistent_storage):
    # Make sure container isn't already running
    existing_containers = client.containers.list(all=True, filters={'name': container_name})
    if len(existing_containers) > 0:
        if not click.confirm(f"{container_name} container already exists. Would you like to delete it and create a new one?",
                         default=False):
            print(f"Skipping {container_name} setup...")
            return False

        print(f"Deleting old {container_name}...")
        existing_containers[0].stop()
        existing_containers[0].remove()

    # Check to see if persistent storage already exists
    if os.path.exists(persistent_storage) and len(os.listdir(persistent_storage)) > 0:
        if not click.confirm(f"Data for {container_name} already exists in {persistent_storage}. Would you like to delete it?",
                         default=False):
            print(f"Skipping {container_name} setup...")
            return False

        print(f"Deleting {persistent_storage}...")
        shutil.rmtree(persistent_storage)

    return True


def get_admin_user(users):
    admin_user = [user for user in users if user['role'] == 'admin']
    if len(admin_user) > 1:
        print("Error: Only one admin user is support at this time.")
        exit()
    elif len(admin_user) <= 0:
        print("Error: At least one admin user must be included.")
        exit()
    else:
        admin_user = admin_user[0]

    return admin_user


def generate_password(length=32):
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password







if __name__ == '__main__':
    main()
