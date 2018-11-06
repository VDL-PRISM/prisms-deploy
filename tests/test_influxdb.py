

def test_database(influx_client):
    dbs = influx_client.get_list_database()
    assert len(dbs) == 2

    for db in dbs:
        assert db['name'] in ['_internal', 'epifi']


def test_users(influx_client):
    users = influx_client.get_list_users()
    assert len(users) == 6
