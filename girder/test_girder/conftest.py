import os
import subprocess

import pytest

pytestmark = pytest.mark.girder


@pytest.fixture
def unavailableWorker(db):
    """
    Make sure that Girder Worker can't be reached and times out quickly.
    """
    from girder_plugin_worker.constants import PluginSettings as WorkerSettings

    from girder.models.setting import Setting

    # Use an invalid broker to make sure we don't connect to girder_worker so
    # this will be incomplete.  We don't want to use amqp as it will retry a
    # very long time.  The mongodb backend is deprecated and throws many
    # warnings, but works for this test condition.
    Setting().set(WorkerSettings.BROKER, 'mongodb://0.0.0.0')
    Setting().set(WorkerSettings.BACKEND, 'mongodb://0.0.0.0')
    yield True
    Setting().unset(WorkerSettings.BROKER)
    Setting().unset(WorkerSettings.BACKEND)


@pytest.fixture(scope='session')
def girderWorkerProcess():
    broker = 'amqp://guest@127.0.0.1'
    backend = 'rpc://guest@127.0.0.1'
    env = os.environ.copy()
    env['C_FORCE_ROOT'] = 'true'
    proc = subprocess.Popen([
        'celery', '-A', 'girder_worker.app', '--broker', broker,
        '--result-backend', backend, 'worker', '--concurrency=1'],
        close_fds=True, env=env)
    yield True
    proc.terminate()
    proc.wait()


@pytest.fixture
def girderWorker(db, girderWorkerProcess):
    """
    Run an instance of Girder worker, connected to rabbitmq.  The rabbitmq
    service must be running.
    """
    from girder_plugin_worker.constants import PluginSettings as WorkerSettings

    from girder.models.setting import Setting

    broker = 'amqp://guest@127.0.0.1'
    backend = 'rpc://guest@127.0.0.1'
    Setting().set(WorkerSettings.BROKER, broker)
    Setting().set(WorkerSettings.BACKEND, backend)
    yield True
    Setting().unset(WorkerSettings.BROKER)
    Setting().unset(WorkerSettings.BACKEND)


def unbindGirderEventsByHandlerName(handlerName):
    from girder import events

    for eventName in events._mapping:
        events.unbind(eventName, handlerName)


@pytest.fixture
def unbindLargeImage(db):
    yield True
    unbindGirderEventsByHandlerName('large_image')
