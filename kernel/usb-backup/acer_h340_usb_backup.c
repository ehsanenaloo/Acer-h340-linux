// SPDX-License-Identifier: GPL-2.0-only
/*
 * ACPI input bridge restricted to the Acer H340 examined in this task.
 * The firmware sends Notify(\\_SB.MBTN, 0x80) from GPE _L18.
 * Unlike the generic Direct App Launch interface, this firmware's MBTN
 * declaration has no GHID. The role is established by the model-specific
 * DSDT and a press of the physical button, not by a guessed GHID value.
 *
 * This driver only emits input events. It performs no port I/O, firmware
 * method evaluation, disk access, backup execution or wakeup configuration.
 */
#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/input.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/string.h>

struct h340_backup_button {
	acpi_handle handle;
	struct input_dev *input;
	struct mutex lock;
	char phys[64];
};

static bool h340_dmi_equals(int field, const char *expected)
{
	const char *value = dmi_get_system_info(field);
	char *copy;
	bool matches;

	if (!value)
		return false;
	copy = kstrdup(value, GFP_KERNEL);
	if (!copy)
		return false;
	matches = !strcmp(strim(copy), expected);
	kfree(copy);
	return matches;
}

static void h340_backup_notify(acpi_handle handle, u32 event, void *context)
{
	struct h340_backup_button *button = context;

	/* Runtime presses only; never convert wakeup or unknown notices to copy. */
	if (event != 0x80)
		return;
	mutex_lock(&button->lock);
	input_report_key(button->input, KEY_COPY, 1);
	input_sync(button->input);
	input_report_key(button->input, KEY_COPY, 0);
	input_sync(button->input);
	mutex_unlock(&button->lock);
}

static void h340_remove_notify(void *context)
{
	struct h340_backup_button *button = context;

	acpi_remove_notify_handler(button->handle, ACPI_DEVICE_NOTIFY,
				  h340_backup_notify);
}

static void h340_destroy_mutex(void *context)
{
	struct h340_backup_button *button = context;

	mutex_destroy(&button->lock);
}

static int h340_backup_probe(struct platform_device *pdev)
{
	struct h340_backup_button *button;
	acpi_status status;
	int ret;

	if (!h340_dmi_equals(DMI_SYS_VENDOR, "Acer") ||
	    !h340_dmi_equals(DMI_PRODUCT_NAME, "Aspire easyStore H340") ||
	    !h340_dmi_equals(DMI_BOARD_NAME, "WG945GCM"))
		return -ENODEV;
	if (!ACPI_HANDLE(&pdev->dev))
		return -ENODEV;

	button = devm_kzalloc(&pdev->dev, sizeof(*button), GFP_KERNEL);
	if (!button)
		return -ENOMEM;
	button->handle = ACPI_HANDLE(&pdev->dev);
	button->input = devm_input_allocate_device(&pdev->dev);
	if (!button->input)
		return -ENOMEM;
	mutex_init(&button->lock);
	ret = devm_add_action_or_reset(&pdev->dev, h340_destroy_mutex, button);
	if (ret)
		return ret;

	snprintf(button->phys, sizeof(button->phys), "%s/input0",
		 dev_name(&pdev->dev));
	button->input->name = "Acer H340 USB Backup";
	button->input->phys = button->phys;
	button->input->id.bustype = BUS_HOST;
	button->input->dev.parent = &pdev->dev;
	input_set_capability(button->input, EV_KEY, KEY_COPY);
	ret = input_register_device(button->input);
	if (ret)
		return ret;

	status = acpi_install_notify_handler(button->handle, ACPI_DEVICE_NOTIFY,
					    h340_backup_notify, button);
	if (ACPI_FAILURE(status))
		return -EIO;
	return devm_add_action_or_reset(&pdev->dev, h340_remove_notify, button);
}

static const struct acpi_device_id h340_backup_ids[] = {
	{ "PNP0C32", 0 },
	{ }
};
MODULE_DEVICE_TABLE(acpi, h340_backup_ids);

static struct platform_driver h340_backup_driver = {
	.probe = h340_backup_probe,
	.driver = {
		.name = "acer-h340-usb-backup",
		.acpi_match_table = h340_backup_ids,
	},
};
module_platform_driver(h340_backup_driver);

MODULE_DESCRIPTION("Acer H340 ACPI USB Backup input bridge");
MODULE_LICENSE("GPL");
