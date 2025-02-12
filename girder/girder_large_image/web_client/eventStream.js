/* This implements a polling fallback if event streams are disabled on the
 * server. */

import largeImageConfig from './views/configView';

const eventStream = girder.utilities.eventStream;
const {restRequest} = girder.rest;

eventStream.on('g:eventStream.disable', () => {
    largeImageConfig.getSettings(() => {
        if (largeImageConfig.settings['large_image.notification_stream_fallback'] === false) {
            return;
        }
        const MIN_TIMEOUT = 5000;
        const MAX_TIMEOUT = 60000;
        const TIMEOUT_FALLOFF = 1000;
        let pollCallback;
        let timeout = MIN_TIMEOUT;
        let lastTimestamp;
        try {
            lastTimestamp = window.localStorage.getItem('sseFallbackTimestamp');
            if (lastTimestamp === 'null' || lastTimestamp === 'undefined') {
                lastTimestamp = undefined;
            }
        } catch (e) {
            // Ignore any errors raised by localStorage
        }

        function checkNotifications() {
            pollCallback = null;
            restRequest({
                url: 'notification',
                data: {
                    since: lastTimestamp || undefined
                },
                error: null
            }).done((resp) => {
                if (!resp.length) {
                    if (timeout < MAX_TIMEOUT) {
                        timeout += TIMEOUT_FALLOFF;
                    }
                } else {
                    timeout = MIN_TIMEOUT;
                }
                resp.forEach((obj) => {
                    lastTimestamp = obj.time || lastTimestamp;
                    try {
                        eventStream.trigger('g:event.' + obj.type, obj);
                    } catch (e) {
                        // ignore errors
                    }
                });
                try {
                    window.localStorage.setItem('sseFallbackTimestamp', lastTimestamp);
                } catch (e) {
                    // Ignore any errors raised by localStorage
                }
                pollCallback = window.setTimeout(checkNotifications, timeout);
            }).fail(() => {
                if (timeout < MAX_TIMEOUT) {
                    timeout += TIMEOUT_FALLOFF;
                }
                pollCallback = window.setTimeout(checkNotifications, timeout);
            });
        }

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                timeout = MIN_TIMEOUT;
                if (!pollCallback) {
                    pollCallback = window.setTimeout(checkNotifications, timeout);
                    eventStream.trigger('g:eventStream.start');
                }
            } else if (pollCallback) {
                window.clearTimeout(pollCallback);
                eventStream.trigger('g:eventStream.stop');
                pollCallback = null;
            }
        });
        pollCallback = window.setTimeout(checkNotifications, timeout);
    });
});
