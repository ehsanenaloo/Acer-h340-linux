#!/usr/bin/env dash
set -e

. /usr/share/openmediavault/scripts/helper-functions

# Look at the node, not at the model: stored settings of an older version fail
# the model check and must not be mistaken for missing settings.
if ! omv_config_exists "/config/services/h340"; then
	omv-confdbadm read --defaults "conf.service.h340" | omv-confdbadm update "conf.service.h340" -
	# OpenMediaVault ships the power button as "nothing". On a fresh install of
	# this plugin the front button should shut the NAS down, as its owner expects.
	# An existing choice is never changed, and an upgrade never reaches this branch.
	if [ "$(omv_config_get "/config/system/powermanagement/powerbtn")" = "nothing" ]; then
		omv_config_update "/config/system/powermanagement/powerbtn" "shutdown"
		omv_module_set_dirty "systemd-logind"
	fi
fi

exit 0
