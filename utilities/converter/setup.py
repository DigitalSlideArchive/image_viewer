import os

from setuptools import find_packages, setup

with open('README.rst') as fh:
    readme = fh.read()

description = 'Converter for Large Image.'
long_description = readme


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

setup(
    name='large-image-converter',
    use_scm_version={'root': '../..', 'local_scheme': prerelease_local_scheme,
                     'fallback_version': '0.0.0'},
    description=description,
    long_description=long_description,
    long_description_content_type='text/x-rst',
    license='Apache Software License 2.0',
    author='Kitware Inc',
    author_email='kitware@kitware.com',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Apache Software License',
        'Topic :: Scientific/Engineering',
        'Intended Audience :: Science/Research',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
    ],
    install_requires=[
        f'large-image-source-tiff{limit_version}',
        'numpy',
        'psutil',
        'pyvips',
        'tifftools',
    ],
    extras_require={
        'jp2k': [
            'glymur',
        ],
        'geospatial': [
            'gdal',
        ],
        'sources': [
            f'large-image[sources]{limit_version}',
        ],
        'stats': [
            'packaging',
            'scikit-image',
        ],
        'all': [
            'glymur',
            'gdal',
            f'large-image[sources]{limit_version}',
            'packaging',
            'scikit-image',
        ],
    },
    packages=find_packages(),
    entry_points={
        'console_scripts': ['large_image_converter = large_image_converter.__main__:main'],
    },
    python_requires='>=3.8',
)
