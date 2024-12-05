# Build wheels
FROM python:3.12-slim as build

# Need git for setuptools_scm
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && apt-get purge -y --auto-remove \
    && rm -rf /var/lib/apt/lists/*

COPY . /opt/build-context/
WORKDIR /opt/build-context

RUN python -m pip install --upgrade pip wheel setuptools
RUN sh .circleci/make_wheels.sh
RUN mv ~/wheels /opt/build-context/

RUN echo "pylibmc>=1.5.1\nmatplotlib\npyvips\nsimplejpeg\n" \
    > /opt/build-context/wheels/requirements.txt


# Geospatial Sources
FROM python:3.12-slim as geo
COPY --from=build /opt/build-context/wheels /opt/wheels
LABEL maintainer="Kitware, Inc. <kitware@kitware.com>"
LABEL repo="https://github.com/girder/large_image"
# NOTE: this does not install any girder3 packages
RUN pip install \
    --find-links https://girder.github.io/large_image_wheels \
    --find-links=/opt/wheels \
    -r /opt/wheels/requirements.txt \
    /opt/wheels/large_image-*.whl \
    /opt/wheels/large_image_source_gdal*.whl \
    /opt/wheels/large_image_source_mapnik*.whl \
    /opt/wheels/large_image_source_tiff*.whl \
    /opt/wheels/large_image_source_pil*.whl \
    /opt/wheels/large_image_converter*.whl


# All Sources
FROM python:3.12-slim as all
COPY --from=build /opt/build-context/wheels /opt/wheels
LABEL maintainer="Kitware, Inc. <kitware@kitware.com>"
LABEL repo="https://github.com/girder/large_image"
# NOTE: this does not install any girder3 packages
RUN pip install \
    --find-links https://girder.github.io/large_image_wheels \
    --find-links=/opt/wheels \
    -r /opt/wheels/requirements.txt \
    /opt/wheels/large_image-*.whl \
    /opt/wheels/large_image_converter*.whl \
    $(ls -1  /opt/wheels/large_image_source*.whl)


# All Sources and Girder Packages
FROM python:3.12-slim as girder
COPY --from=build /opt/build-context/wheels /opt/wheels
LABEL maintainer="Kitware, Inc. <kitware@kitware.com>"
LABEL repo="https://github.com/girder/large_image"
# NOTE: this does not install any girder3 packages
RUN pip install \
    --find-links https://girder.github.io/large_image_wheels \
    --find-links=/opt/wheels \
    -r /opt/wheels/requirements.txt \
    $(ls -1  /opt/wheels/*.whl)


# Jupyter all sources
FROM jupyter/base-notebook:python-3.11.6 as jupyter
COPY --from=build /opt/build-context/wheels /opt/wheels
LABEL maintainer="Kitware, Inc. <kitware@kitware.com>"
LABEL repo="https://github.com/girder/large_image"
RUN pip install \
    --find-links https://girder.github.io/large_image_wheels \
    --find-links=/opt/wheels \
    -r /opt/wheels/requirements.txt \
    /opt/wheels/large_image-*.whl \
    /opt/wheels/large_image_converter*.whl \
    $(ls -1  /opt/wheels/large_image_source*.whl)
RUN pip install \
    ipyleaflet \
    jupyter-server-proxy
ENV LARGE_IMAGE_JUPYTER_PROXY='/proxy/'


# Jupyter Geospatial sources
FROM jupyter/base-notebook:python-3.11.6 as jupyter-geo
COPY --from=build /opt/build-context/wheels /opt/wheels
LABEL maintainer="Kitware, Inc. <kitware@kitware.com>"
LABEL repo="https://github.com/girder/large_image"
# NOTE: this does not install any girder3 packages
RUN pip install \
    --find-links https://girder.github.io/large_image_wheels \
    --find-links=/opt/wheels \
    -r /opt/wheels/requirements.txt \
    /opt/wheels/large_image-*.whl \
    /opt/wheels/large_image_source_gdal*.whl \
    /opt/wheels/large_image_source_mapnik*.whl \
    /opt/wheels/large_image_source_tiff*.whl \
    /opt/wheels/large_image_source_pil*.whl \
    /opt/wheels/large_image_converter*.whl
RUN pip install \
    ipyleaflet \
    jupyter-server-proxy
ENV LARGE_IMAGE_JUPYTER_PROXY='/proxy/'
