#!/usr/bin/env dash
set -e

. /usr/share/openmediavault/scripts/helper-functions

# Settings added in 0.2.0. Defaults match the data model.
omv_config_add_key "/config/services/h340" "ledenable" "0"
omv_config_add_key "/config/services/h340" "bay1" ""
omv_config_add_key "/config/services/h340" "bay2" ""
omv_config_add_key "/config/services/h340" "bay3" ""
omv_config_add_key "/config/services/h340" "bay4" ""

exit 0
