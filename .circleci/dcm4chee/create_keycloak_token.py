#!/usr/bin/env python3

# This script can be used to create a keycloak token for the
# dcm4chee server via the python-keycloak API. python-keycloak
# must be installed.

from keycloak import KeycloakOpenID

keycloack_openid = KeycloakOpenID(
    server_url='https://localhost:8843',
    client_id='dcm4chee-arc-rs',
    realm_name='dcm4che',
    client_secret_key='changeit',
    # Certificate is not working, just don't verify...
    verify=False,
)

token_dict = keycloack_openid.token('user', 'changeit')
print(token_dict['access_token'])
