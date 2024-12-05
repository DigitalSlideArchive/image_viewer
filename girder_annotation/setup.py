import os

from setuptools import find_packages, setup

description = 'A Girder plugin to store and display annotations on large, multiresolution images.'
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

    version = get_version(root='..', local_scheme=prerelease_local_scheme)
    limit_version = f'>={version}' if '+' not in version and not os.getenv('TOX_ENV_NAME') else ''
except (ImportError, LookupError):
    limit_version = ''

setup(
    name='girder-large-image-annotation',
    use_scm_version={'root': '..', 'local_scheme': prerelease_local_scheme,
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
        'jsonschema>=2.5.1',
        f'girder-large-image{limit_version}',
        'orjson',
    ],
    extras_require={
        'compute': [
            'openpyxl',
            'pandas ; python_version < "3.9"',
            'pandas>=2.2 ; python_version >= "3.9"',
            'python-calamine ; python_version >= "3.9"',
            'umap-learn ; python_version < "3.13"',
        ],
        'tasks': [
            f'girder-large-image[tasks]{limit_version}',
        ],
    },
    include_package_data=True,
    keywords='girder-plugin, large_image',
    packages=find_packages(exclude=['test', 'test.*', 'test_annotation', 'test_annotation.*']),
    python_requires='>=3.8',
    url='https://github.com/girder/large_image',
    zip_safe=False,
    entry_points={
        'girder.plugin': [
            'large_image_annotation = girder_large_image_annotation:LargeImageAnnotationPlugin',
        ],
    },
)
