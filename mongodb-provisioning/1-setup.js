db.createCollection("deployments")

db.createUser({user:'status_reader', pwd:'password', roles:[{role:'read', db:'prisms'}]});
db.createUser({user:'mqtt_reader', pwd:'password', roles:[{role:'read', db:'prisms'}]});
db.createUser({user:'prisms', pwd:'password', roles:[{role:'readWrite', db:'prisms'}]});
