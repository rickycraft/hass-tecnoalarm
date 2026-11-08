"""Integration constants."""

DOMAIN = "tecnoalarm"
CONF_POLLING_INTERVAL = "polling_interval"
DEFAULT_POLLING_INTERVAL = 30
MAX_POLLING_INTERVAL = 600
# Legacy options are read for compatibility and removed when settings are saved.
CONF_PERSISTENT_CONNECTION = "persistent_connection"
CONF_POLLING = "polling"


def polling_interval(options):
    """Read the interval, preserving an explicitly selected legacy open session."""
    return options.get(CONF_POLLING_INTERVAL,
                       0 if options.get(CONF_PERSISTENT_CONNECTION) else DEFAULT_POLLING_INTERVAL)
