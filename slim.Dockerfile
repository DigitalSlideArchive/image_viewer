# Build wheels
FROM python:3.13-slim AS build

# Need git for setuptools_scm
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && apt-get purge -y --auto-remove \
    && rm -rf /var/lib/apt/lists/*

RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash && \
    . ~/.bashrc && \
    nvm install --lts && \
    nvm alias default lts/* && \
    nvm use default && \
    rm -rf /root/.nvm/.cache && \
    ln -s $(dirname `which npm`) /usr/local/node

COPY . /opt/build-context/
WORKDIR /opt/build-context

RUN python -m pip install --upgrade pip wheel setuptools
RUN PATH="$PATH:/usr/local/node" bash .circleci/release_pypi.sh skip
RUN mv ~/wheels /opt/build-context/

RUN echo "pylibmc>=1.5.1\nmatplotlib\npyvips\nsimplejpeg\n" \
    > /opt/build-context/wheels/requirements.txt


# Geospatial Sources
FROM python:3.13-slim AS geo
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
FROM python:3.13-slim AS all
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
FROM python:3.13-slim AS girder
COPY --from=build /opt/build-context/wheels /opt/wheels
LABEL maintainer="Kitware, Inc. <kitware@kitware.com>"
LABEL repo="https://github.com/girder/large_image"
# NOTE: this does not install any girder packages
RUN pip install \
    --find-links https://girder.github.io/large_image_wheels \
    --find-links=/opt/wheels \
    -r /opt/wheels/requirements.txt \
    $(ls -1  /opt/wheels/*.whl)


# Jupyter all sources
FROM jupyter/base-notebook:python-3.11.6 AS jupyter
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
FROM jupyter/base-notebook:python-3.11.6 AS jupyter-geo
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
