<?php

namespace Engined\Rpc;

class OMVRpcServiceH340 extends \OMV\Rpc\ServiceAbstract
{
    private const COPY_STATE_FILE = "/run/h340-usb-backup/state.json";
    private const LAST_RUN_FILE = "/var/lib/h340-usb-backup/last-run.json";
    private const LED_RUN_DIR = "/run/h340-leds";
    private const BAY_STATUS_FILE = "/run/h340-leds/status.json";
    private const LOGIND_DROPIN_DIR = "/etc/systemd/logind.conf.d";

    public function getName()
    {
        return "H340";
    }

    public function initialize()
    {
        $this->registerMethod("getBackupSettings");
        $this->registerMethod("setBackupSettings");
        $this->registerMethod("getLedSettings");
        $this->registerMethod("setLedSettings");
        $this->registerMethod("getPowerSettings");
        $this->registerMethod("setPowerSettings");
        $this->registerMethod("getStatus");
    }

    private function pick($assoc, $keys)
    {
        return array_intersect_key($assoc, array_flip($keys));
    }

    /**
     * Get the USB backup settings.
     */
    public function getBackupSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $db = \OMV\Config\Database::getInstance();
        $object = $db->get("conf.service.h340");
        return $this->pick($object->getAssoc(), [
            "enable", "sharedfolderref", "reldirpath", "reservemib",
            "label", "excludes"
        ]);
    }

    /**
     * Set the USB backup settings. The copy rules that protect data (no
     * delete, no overwrite, read-only source) are fixed and not settings.
     */
    public function setBackupSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.h340.setbackupsettings");
        $relDirPath = trim($params['reldirpath'], "/");
        if (1 === preg_match('/(^|\/)\.\.?(\/|$)|\/\/|[\x00-\x1f\\\\]/', $relDirPath)) {
            throw new \OMV\Exception(
                gettext("The sub-folder must not contain '.', '..' or control characters.")
            );
        }
        $params['reldirpath'] = $relDirPath;
        if (true === boolval($params['enable']) &&
                "" === $params['sharedfolderref']) {
            throw new \OMV\Exception(
                gettext("Select a shared folder for the backups.")
            );
        }
        foreach (preg_split('/\R/', $params['excludes']) as $pattern) {
            $pattern = trim($pattern);
            if ("" !== $pattern && (false !== strpos($pattern, "/") ||
                    255 < strlen($pattern))) {
                throw new \OMV\Exception(
                    gettext("An exclude pattern matches one name and must not contain '/'.")
                );
            }
        }
        $db = \OMV\Config\Database::getInstance();
        if ("" !== $params['sharedfolderref']) {
            // Fails when the shared folder does not exist.
            $db->get("conf.system.sharedfolder", $params['sharedfolderref']);
        }
        $object = $db->get("conf.service.h340");
        $object->setAssoc(array_merge($object->getAssoc(), $params));
        $db->set($object);
        return $this->pick($object->getAssoc(), array_keys($params));
    }

    /**
     * Get the LED settings. "forgetmissing" is an action, never stored.
     */
    public function getLedSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $db = \OMV\Config\Database::getInstance();
        $object = $db->get("conf.service.h340");
        $settings = $this->pick($object->getAssoc(), ["ledenable"]);
        $settings['forgetmissing'] = false;
        return $settings;
    }

    /**
     * Set the LED settings. Which disk sits in which bay is read from the
     * system (the SATA port), so it is not a setting. Register mapping,
     * polarity and fan input are measured facts of this machine.
     * Saving with "forgetmissing" asks the service to drop disks that are
     * no longer installed, so their bays stop showing a fault.
     */
    public function setLedSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.h340.setledsettings");
        $forget = boolval($params['forgetmissing']);
        unset($params['forgetmissing']);
        $db = \OMV\Config\Database::getInstance();
        $object = $db->get("conf.service.h340");
        $object->setAssoc(array_merge($object->getAssoc(), $params));
        $db->set($object);
        if (true === $forget && is_dir(self::LED_RUN_DIR)) {
            file_put_contents(self::LED_RUN_DIR . "/forget-missing", "");
        }
        $settings = $this->pick($object->getAssoc(), ["ledenable"]);
        $settings['forgetmissing'] = false;
        return $settings;
    }

    /**
     * Format a time in the server's time zone. OMV's PHP default is UTC, which
     * would show a copy at the wrong hour on a server set to another zone.
     */
    private function formatTime($timestamp)
    {
        // Debian 13 has no /etc/timezone; the zone is the /etc/localtime link.
        $zone = "";
        $link = @readlink("/etc/localtime");
        if (false !== $link && 1 === preg_match('#zoneinfo/(.+)$#', $link, $match)) {
            $zone = $match[1];
        } else {
            $zone = @trim((string)@file_get_contents("/etc/timezone"));
        }
        try {
            $tz = new \DateTimeZone("" !== $zone ? $zone : "UTC");
        } catch (\Exception $e) {
            $tz = new \DateTimeZone("UTC");
        }
        return (new \DateTime("@" . intval($timestamp)))
            ->setTimezone($tz)
            ->format("Y-m-d H:i:s T");
    }

    /**
     * The power button action is OpenMediaVault's own setting (System > Power
     * management); this page reads and writes the same object, so there is one
     * source of truth and OMV deploys it to systemd-logind.
     */
    private function powerChoice($object)
    {
        switch ($object->get("powerbtn")) {
            case "nothing":
                return "nothing";
            case "standby":
                // Standby only sleeps when OMV's standby mode is suspend.
                return "suspend" === $object->get("standbymode") ? "sleep" : "shutdown";
            default:
                return "shutdown";
        }
    }

    /**
     * Get the power button action.
     */
    public function getPowerSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $db = \OMV\Config\Database::getInstance();
        return ["powerbutton" => $this->powerChoice($db->get("conf.system.powermngmnt"))];
    }

    /**
     * Set the power button action: shut down, sleep (suspend to RAM) or nothing.
     */
    public function setPowerSettings($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $this->validateMethodParams($params, "rpc.h340.setpowersettings");
        $db = \OMV\Config\Database::getInstance();
        $object = $db->get("conf.system.powermngmnt");
        switch ($params['powerbutton']) {
            case "nothing":
                $object->set("powerbtn", "nothing");
                break;
            case "sleep":
                $object->set("powerbtn", "standby");
                $object->set("standbymode", "suspend");
                break;
            default:
                $object->set("powerbtn", "shutdown");
                break;
        }
        $db->set($object);
        return ["powerbutton" => $this->powerChoice($object)];
    }

    private function readJson($file)
    {
        $text = @file_get_contents($file);
        if (false === $text) {
            return null;
        }
        $data = json_decode($text, true);
        return is_array($data) ? $data : null;
    }

    /**
     * Report the services, a copy in progress and the last finished copy.
     */
    public function getStatus($params, $context)
    {
        $this->validateMethodContext($context, [
            "role" => OMV_ROLE_ADMINISTRATOR
        ]);
        $lines = [];
        $runner = new \OMV\System\SystemCtl("h340-usb-backup");
        $leds = new \OMV\System\SystemCtl("h340-leds");
        $lines[] = sprintf(
            "%s: %s",
            gettext("Backup service"),
            $runner->isActive() ? gettext("running") : gettext("stopped")
        );
        $lines[] = sprintf(
            "%s: %s",
            gettext("LED service"),
            $leds->isActive() ? gettext("running") : gettext("stopped")
        );
        $db = \OMV\Config\Database::getInstance();
        $names = [
            "shutdown" => gettext("shut down"),
            "sleep" => gettext("sleep"),
            "nothing" => gettext("do nothing")
        ];
        $choice = $this->powerChoice($db->get("conf.system.powermngmnt"));
        $effective = trim((string)@shell_exec(
            "busctl get-property org.freedesktop.login1 /org/freedesktop/login1 " .
            "org.freedesktop.login1.Manager HandlePowerKey 2>/dev/null"
        ));
        $lines[] = sprintf(
            "%s: %s (%s: %s)",
            gettext("Power button"),
            $names[$choice],
            gettext("system"),
            1 === preg_match('/"([a-z-]+)"/', $effective, $match) ? $match[1] : gettext("unknown")
        );
        foreach (glob(self::LOGIND_DROPIN_DIR . "/*.conf") ?: [] as $dropin) {
            if (1 === preg_match('/^\s*HandlePowerKey\s*=/m', (string)@file_get_contents($dropin))) {
                $lines[] = sprintf(
                    "  %s: %s",
                    gettext("overridden by a manual file, the setting has no effect"),
                    $dropin
                );
            }
        }
        $button = false;
        foreach (glob("/sys/class/input/event*/device/name") ?: [] as $nameFile) {
            if ("Acer H340 USB Backup" === trim((string)@file_get_contents($nameFile))) {
                $button = true;
            }
        }
        $lines[] = sprintf(
            "%s: %s",
            gettext("USB Backup button"),
            $button ? gettext("detected") : gettext("not detected (the kernel module is not loaded)")
        );
        $bays = $this->readJson(self::BAY_STATUS_FILE);
        $texts = [
            "ok" => gettext("in use"),
            "new" => gettext("new disk, not in use yet"),
            "missing" => gettext("missing")
        ];
        for ($bay = 0; $bay < 4; $bay++) {
            $info = $bays['bays'][(string)$bay] ?? null;
            $lines[] = sprintf(
                "%s %d: %s",
                gettext("Bay"),
                $bay + 1,
                is_array($info)
                    ? sprintf(
                        "%s (%s)",
                        $info['identity'] ?? gettext("unknown disk"),
                        $texts[$info['state'] ?? ""] ?? gettext("unknown")
                    )
                    : gettext("empty")
            );
        }
        $state = $this->readJson(self::COPY_STATE_FILE);
        $now = time();
        if (is_array($state) && "copying" === ($state['state'] ?? "") &&
                30 >= $now - intval($state['updated'] ?? 0)) {
            $lines[] = sprintf(
                "%s: %s (%d / %d)",
                gettext("Copy now"),
                gettext("in progress"),
                intval($state['copied'] ?? 0),
                intval($state['total'] ?? 0)
            );
        } else {
            $lines[] = sprintf("%s: %s", gettext("Copy now"), gettext("none"));
        }
        $last = $this->readJson(self::LAST_RUN_FILE);
        if (null === $last) {
            $lines[] = sprintf(
                "%s: %s",
                gettext("Last copy"),
                gettext("no copy recorded")
            );
        } else {
            $lines[] = sprintf(
                "%s: %s, %s",
                gettext("Last copy"),
                $this->formatTime($last['finished'] ?? 0),
                !empty($last['ok']) ? gettext("verified") : gettext("not complete")
            );
            $lines[] = sprintf(
                "  %s: %d / %d, %s: %d, %s: %d",
                gettext("files copied"),
                intval($last['copied'] ?? 0),
                intval($last['total'] ?? 0),
                gettext("skipped"),
                intval($last['skipped'] ?? 0),
                gettext("excluded"),
                intval($last['excluded'] ?? 0)
            );
            if (!empty($last['run_dir'])) {
                $lines[] = sprintf("  %s: %s", gettext("folder"), $last['run_dir']);
            }
            if (!empty($last['error'])) {
                $lines[] = sprintf("  %s: %s", gettext("problem"), $last['error']);
            }
        }
        return implode("\n", $lines) . "\n";
    }
}
