#!/usr/bin/env python3

import urllib.request
from io import BytesIO

from dicomweb_client import DICOMwebClient
from pydicom import dcmread
from requests import Session
from tenacity import Retrying, stop_after_attempt, wait_exponential


def upload_example_data(server_url, token=None):

    # This is TCGA-AA-3697
    sha512s = [
        '48cb562b94d0daf4060abd9eef150c851d3509d9abbff4bea11d00832955720bf1941073a51e6fb68fb5cc23704dec2659fc0c02360a8ac753dc523dca2c8c36',  # noqa
        '36432183380eb7d44417a2210a19d550527abd1181255e19ed5c1d17695d8bb8ca42f5b426a63fa73b84e0e17b770401a377ae0c705d0ed7fdf30d571ef60e2d',  # noqa
        '99bd3da4b8e11ce7b4f7ed8a294ed0c37437320667a06c40c383f4b29be85fe8e6094043e0600bee0ba879f2401de4c57285800a4a23da2caf2eb94e5b847ee0',  # noqa
    ]
    download_urls = [
        f'https://data.kitware.com/api/v1/file/hashsum/sha512/{x}/download' for x in sha512s
    ]

    datasets = []
    for url in download_urls:
        for attempt in Retrying(stop=stop_after_attempt(5),
                                wait=wait_exponential(multiplier=1, min=0.5, max=5)):
            with attempt:
                resp = urllib.request.urlopen(url)
                data = resp.read()
        dataset = dcmread(BytesIO(data))
        datasets.append(dataset)

    if token is not None:
        session = Session()
        session.headers.update({'Authorization': f'Bearer {token}'})
    else:
        session = None

    client = DICOMwebClient(server_url, session=session)
    client.store_instances(datasets)


if __name__ == '__main__':
    import os

    url = os.getenv('DICOMWEB_TEST_URL')
    if url is None:
        msg = 'DICOMWEB_TEST_URL must be set'
        raise Exception(msg)

    token = os.getenv('DICOMWEB_TEST_TOKEN')
    upload_example_data(url, token=token)
