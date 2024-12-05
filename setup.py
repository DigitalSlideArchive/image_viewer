import itertools
import os

from setuptools import setup


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

    version = get_version(local_scheme=prerelease_local_scheme)
    limit_version = f'>={version}' if '+' not in version and not os.getenv('TOX_ENV_NAME') else ''
except (ImportError, LookupError):
    limit_version = ''

with open('README.rst') as readme_file:
    readme = readme_file.read()
description = 'Python modules to work with large, multiresolution images.'
long_description = readme

extraReqs = {
    'memcached': ['pylibmc>=1.5.1 ; platform_system != "Windows"'],
    'redis': ['redis>=4.5.5'],
    'converter': [f'large-image-converter{limit_version}'],
    'colormaps': ['matplotlib'],
    'tiledoutput': ['pyvips'],
    'performance': [
        'psutil>=4.2.0',
        'simplejpeg',
    ],
}
sources = {
    'bioformats': [f'large-image-source-bioformats{limit_version}'],
    'deepzoom': [f'large-image-source-deepzoom{limit_version}'],
    'dicom': [f'large-image-source-dicom{limit_version}'],
    'dummy': [f'large-image-source-dummy{limit_version}'],
    'gdal': [f'large-image-source-gdal{limit_version}'],
    'mapnik': [f'large-image-source-mapnik{limit_version}'],
    'multi': [f'large-image-source-multi{limit_version}'],
    'nd2': [f'large-image-source-nd2{limit_version}'],
    'ometiff': [f'large-image-source-ometiff{limit_version}'],
    'openjpeg': [f'large-image-source-openjpeg{limit_version}'],
    'openslide': [f'large-image-source-openslide{limit_version}'],
    'pil': [f'large-image-source-pil{limit_version}'],
    'rasterio': [f'large-image-source-rasterio{limit_version}'],
    'test': [f'large-image-source-test{limit_version}'],
    'tiff': [f'large-image-source-tiff{limit_version}'],
    'tifffile': [f'large-image-source-tifffile{limit_version}'],
    'vips': [f'large-image-source-vips{limit_version}'],
    'zarr': [f'large-image-source-zarr{limit_version}'],
}
extraReqs.update(sources)
extraReqs['sources'] = list(set(itertools.chain.from_iterable(sources.values())))
extraReqs['all'] = list(set(itertools.chain.from_iterable(extraReqs.values())) | {
    f'large-image-source-multi[all]{limit_version}',
    f'large-image-source-pil[all]{limit_version}',
    f'large-image-source-rasterio[all]{limit_version}',
    f'large-image-source-tiff[all]{limit_version}',
})
# The common packages are ones that will install on Ubuntu, OSX, and Windows
# from pypi with all needed dependencies.
extraReqs['common'] = list(set(itertools.chain.from_iterable(extraReqs[key] for key in {
    'memcached', 'redis', 'colormaps', 'performance',
    'deepzoom', 'dicom', 'multi', 'nd2', 'openslide', 'test', 'tifffile',
    'zarr',
})) | {
    f'large-image-source-pil[all]{limit_version}',
    f'large-image-source-rasterio[all]{limit_version}',
})

setup(
    name='large-image',
    use_scm_version={'local_scheme': prerelease_local_scheme,
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
        'cachetools',
        'palettable',
        'Pillow',
        'numpy',
        'typing-extensions',
    ],
    extras_require=extraReqs,
    include_package_data=True,
    keywords='large_image',
    packages=['large_image'],
    url='https://github.com/girder/large_image',
    python_requires='>=3.8',
    zip_safe=False,
)
