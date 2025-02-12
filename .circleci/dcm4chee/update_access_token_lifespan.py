#!/usr/bin/env python3

# Change the access token life span in the realm settings

import requests
from keycloak import KeycloakOpenIDConnection


def create_openid_admin_token():
    # Get an admin OpenID access token. This expires after 60 seconds.
    return KeycloakOpenIDConnection(
        server_url='https://localhost:8843',
        username='admin',
        password='changeit',
        realm_name='master',
        verify=False,
    ).token['access_token']


def set_access_token_life_span(token, lifespan):
    # curl command looks like this:
    # curl 'https://localhost:8843/admin/realms/dcm4che' \
    #   -X 'PUT' \
    #   -H 'Content-Type: application/json' \
    #   -H 'authorization: Bearer $TOKEN' \
    #   -d '{"accessTokenLifespan":6000}' \
    #   --insecure
    session = requests.Session()
    session.headers.update({'Authorization': f'Bearer {token}'})

    url = 'https://localhost:8843/admin/realms/dcm4che'
    r = session.put(url, json={'accessTokenLifespan': lifespan}, verify=False)
    r.raise_for_status()


if __name__ == '__main__':
    token = create_openid_admin_token()

    # Set default timetout to be 1 hour
    set_access_token_life_span(token, 3600)
