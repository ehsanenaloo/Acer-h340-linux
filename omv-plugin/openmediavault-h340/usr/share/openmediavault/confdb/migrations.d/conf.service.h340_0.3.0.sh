#!/usr/bin/env dash
set -e

. /usr/share/openmediavault/scripts/helper-functions

# The bay of a disk now comes from the system. Drop the per-bay settings.
omv_config_delete "/config/services/h340/bay1"
omv_config_delete "/config/services/h340/bay2"
omv_config_delete "/config/services/h340/bay3"
omv_config_delete "/config/services/h340/bay4"

exit 0
