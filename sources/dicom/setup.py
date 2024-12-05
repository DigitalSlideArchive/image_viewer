import os
import sys

from setuptools import find_packages, setup

description = 'A DICOM tilesource for large_image.'
long_description = description + '\n\nSee the large-image package for more details.'


def prerelease_local_scheme(version):
    """
    Return local scheme version unless building on master in CircleCI.

    This function returns the local scheme version number
    (e.g. 0.0.0.dev<N>+g<HASH>) unless building on CircleCI for a
    pre-release in which case it ignores the hash and produces a
    PEP440 compliant pre-release version number (e.g. 0.0.0.dev<N>).
    """
    from setuptools_scm.version import get_local_node_and_date

    if os.getenv('CIRCLE_BRANCH') in ('master', ):
        return ''
    else:
        return get_local_node_and_date(version)


try:
    from setuptools_scm import get_version

    version = get_version(root='../..', local_scheme=prerelease_local_scheme)
    limit_version = f'>={version}' if '+' not in version and not os.getenv('TOX_ENV_NAME') else ''
except (ImportError, LookupError):
    limit_version = ''

entry_points = {
    'large_image.source': [
        'dicom = large_image_source_dicom:DICOMFileTileSource',
    ],
    'girder_large_image.source': [
        'dicom = large_image_source_dicom.girder_source:DICOMGirderTileSource',
    ],
}

girder_extras = [f'girder-large-image{limit_version}']

if sys.version_info >= (3, 9):
    # For Python >= 3.9, include the DICOMweb plugin
    entry_points['girder.plugin'] = [
        'dicomweb = large_image_source_dicom.girder_plugin:DICOMwebPlugin',
    ]
    girder_extras.append('girder>=3.2.3')

setup(
    name='large-image-source-dicom',
    use_scm_version={'root': '../..', 'local_scheme': prerelease_local_scheme,
                     'fallback_version': '0.0.0'},
    description=description,
    long_description=long_description,
    long_description_content_type='text/x-rst',
    license='Apache Software License 2.0',
    author='Kitware, Inc.',
    author_email='kitware@kitware.com',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
    ],
    install_requires=[
        f'large-image{limit_version}',
        'wsidicom>=0.9.0,!=0.21.3',
        'pydicom<3; python_version < "3.10"',
        'pydicom; python_version >= "3.10"',
    ],
    extras_require={
        'girder': girder_extras,
    },
    include_package_data=True,
    keywords='large_image, tile source',
    packages=find_packages(exclude=['test', 'test.*', 'test_dicom', 'test_dicom.*']),
    url='https://github.com/girder/large_image',
    python_requires='>=3.8',
    entry_points=entry_points,
)
