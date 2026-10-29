<?php

namespace Engined\Module;

class H340 extends \OMV\Engine\Module\ServiceAbstract implements
    \OMV\Engine\Notify\IListener
{
    public function getName()
    {
        return "h340";
    }

    /**
     * Rebuild the configuration when the chosen shared folder changes.
     */
    final public function onSharedFolder($type, $path, $object)
    {
        $db = \OMV\Config\Database::getInstance();
        $settings = $db->get("conf.service.h340");
        if ($settings->get("sharedfolderref") === $object['uuid']) {
            $this->setDirty();
        }
    }

    public function bindListeners(\OMV\Engine\Notify\Dispatcher $dispatcher)
    {
        $dispatcher->addListener(
            OMV_NOTIFY_MODIFY,
            "org.openmediavault.conf.service.h340",
            [$this, "setDirty"]
        );
        $dispatcher->addListener(
            OMV_NOTIFY_MODIFY,
            "org.openmediavault.conf.system.sharedfolder",
            [$this, "onSharedFolder"]
        );
    }
}
