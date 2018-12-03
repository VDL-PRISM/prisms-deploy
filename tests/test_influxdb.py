

def test_database(influx_client):
    dbs = influx_client.get_list_database()

    names = [db['name'] for db in dbs]
    assert 'epifi' in names


def test_users(influx_client):
    users = influx_client.get_list_users()
    assert len(users) == 6
