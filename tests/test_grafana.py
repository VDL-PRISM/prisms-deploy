# Make sure Grafana is up and running

import requests


HOST = 'localhost:3000'


def test_grafana():
    r = requests.get(f'http://{HOST}/')
    assert r.status_code == 200
