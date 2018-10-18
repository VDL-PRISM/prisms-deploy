import os
import secrets
import shutil
import string
import tempfile
import threading
import time

import click
import docker
import influxdb
from jinja2 import Environment, FileSystemLoader
import yaml


MONGODB_CONTAINER_NAME = 'prisms-mongodb'
INFLUX_CONTAINER_NAME = 'prisms-influxdb'
GRAFANA_CONTAINER_NAME = 'prisms-grafana'
MOSQUITTO_CONTAINER_NAME = 'prisms-mosquitto'


def main():
    config = {}
    print("Welcome to the PRISMS architecture setup.")

    print("Let's start with a couple of questions.")
    config['use_lets_encrypt'] = click.confirm("Would you like to use Let's Encrypt to generate certificates?",
                                               default=False)

    if config['use_lets_encrypt']:
        config['lets_encrypt_email'] = click.prompt("What email address do you want to use?")
        config['base_host_name'] = click.prompt("What is the hostname?")

    # client = docker.from_env()

    # mongodb_users = [{'name': 'root',
    #                   'password': generate_password(),
    #                   'role': 'admin'},
    #                  {'name': 'status_reader',
    #                   'password': generate_password(),
    #                   'role': 'read'},
    #                  {'name': 'mqtt_reader',
    #                   'password': generate_password(),
    #                   'role': 'read'}]
    # mongodb_setup(client, mongodb_users)

    # influxdb_users = [{'name': 'admin',
    #                    'password': generate_password(),
    #                    'role': 'admin'},
    #                   {'name': 'status',
    #                    'password': generate_password(),
    #                    'role': 'read'},
    #                   {'name': 'export',
    #                    'password': generate_password(),
    #                    'role': 'read'},
    #                   {'name': 'grafana',
    #                    'password': generate_password(),
    #                    'role': 'read'},
    #                   {'name': 'prisms_subscriber',
    #                    'password': generate_password(),
    #                    'role': 'write'},
    #                   {'name': 'ha_subscriber',
    #                    'password': generate_password(),
    #                    'role': 'write'}]
    # influxdb_setup(client, influxdb_users)

    # grafana_user = {'name': 'admin',
    #                 'password': generate_password()}
    # grafana_setup(client, grafana_user['password'], influxdb_users[3], INFLUX_CONTAINER_NAME)


    mqtt_users = [{'name': 'prisms_subscriber',
                   'password': generate_password(),
                   'topic': 'prisms/v1/#'},
                  {'name': 'prisms_ha_subscriber',
                   'password': generate_password(),
                   'topic': 'prisms/ha/v1/#'}]


    mosquitto_setup(client, mqtt_users)

    # print(mongodb_users)
    # print(influxdb_users)
    # print(grafana_user)



    # Fill in passwords for .env file
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template('env.template')

    print(template.render(**config))
def mosquitto_setup(client, users, persistent_storage='./mosquitto-storage',
                    image='eclipse-mosquitto:latest',
                    root_topic='prisms'):
    print("Setting up Mosquitto")
    persistent_storage = os.path.abspath(persistent_storage)

    if not handle_existing_container(client, MOSQUITTO_CONTAINER_NAME, persistent_storage):
        return

    config_path = os.path.join(persistent_storage, 'config')
    # Make config directory in storage folder
    os.makedirs(os.path.join(config_path, 'certs'))

    # Copy over config file
    shutil.copy('templates/mosquitto.conf', config_path)
    shutil.copy('certs/ca.pem', os.path.join(config_path, 'certs', 'ca.pem'))


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





def grafana_setup(client, admin_password, influxdb_reader_user, influxdb_cointainer_name,
                  persistent_storage='./grafana-storage',
                  database_name='prisms', image='grafana/grafana:latest'):
    print("Setting up Grafana")
    persistent_storage = os.path.abspath(persistent_storage)

    if not handle_existing_container(client, GRAFANA_CONTAINER_NAME, persistent_storage):
        return

    print(f"Pulling {image} (could take awhile)...")
    client.images.pull(image)

    with tempfile.NamedTemporaryFile(dir='.') as f:
        # Set up configuration file
        datasources = {'apiVersion': 1,
                       'datasources': [{'name': 'PRISMS',
                                        'type': 'influxdb',
                                        'access': 'proxy',
                                        'url': f'http://{influxdb_cointainer_name}:8086',
                                        'database': database_name,
                                        'isDefault': True,
                                        'user': influxdb_reader_user['name'],
                                        'password': influxdb_reader_user['password'],
                                        'version': 1,
                                        'editable': True}]}
        f.write(yaml.dump(datasources).encode())
        f.flush()

        container = client.containers.run(
            image,
            name=GRAFANA_CONTAINER_NAME,
            detach=True,
            ports={'3000/tcp': 3000},
            environment={'GF_SECURITY_ADMIN_PASSWORD': admin_password},
            volumes={f.name: {'bind': '/etc/grafana/provisioning/datasources/datasource.yaml',
                              'mode': 'ro'},
                     persistent_storage: {'bind': '/var/lib/grafana', 'mode': 'rw'}})

        print(f"Waiting for {GRAFANA_CONTAINER_NAME} to initialize...")
        wait_for_done(container)

        print(f"Stopping {GRAFANA_CONTAINER_NAME}...")
        container.stop()
        print(f"Removing {GRAFANA_CONTAINER_NAME}...")
        container.remove()


def influxdb_setup(client, users, persistent_storage='./influxdb-storage',
                   database_name='prisms', image='influxdb:1.6'):
    print("Setting up InfluxDB")
    persistent_storage = os.path.abspath(persistent_storage)

    if not handle_existing_container(client, INFLUX_CONTAINER_NAME, persistent_storage):
        return

    print(f"Pulling {image} (could take awhile)...")
    client.images.pull(image)

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


def mongodb_setup(client, users, persistent_storage='./mongodb-storage',
                  database_name='prisms', collection_name='deployments',
                  image='mongo:4.0'):
    print("Setting up MongoDB")
    persistent_storage = os.path.abspath(persistent_storage)

    if not handle_existing_container(client, MONGODB_CONTAINER_NAME, persistent_storage):
        return

    print(f"Pulling {image} (could take awhile)...")
    client.images.pull(image)

    admin_user = get_admin_user(users)
    other_users = [user for user in users if user['role'] != 'admin']

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
