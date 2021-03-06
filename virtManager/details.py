#
# Copyright (C) 2006-2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

import logging
import traceback

# pylint: disable=E0611
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
# pylint: enable=E0611

import libvirt

from virtManager import sharedui
from virtManager import uiutil
from virtManager.storagebrowse import vmmStorageBrowser
from virtManager.baseclass import vmmGObjectUI
from virtManager.addhardware import vmmAddHardware
from virtManager.choosecd import vmmChooseCD
from virtManager.snapshots import vmmSnapshotPage
from virtManager.graphwidgets import Sparkline
from virtManager.fsdetails import vmmFSDetails
from virtinst import VirtualRNGDevice

import virtinst
from virtinst import util


# Parameters that can be editted in the details window
(EDIT_NAME,
EDIT_TITLE,
EDIT_MACHTYPE,
EDIT_DESC,

EDIT_VCPUS,
EDIT_CPUSET,
EDIT_CPU,
EDIT_TOPOLOGY,

EDIT_MEM,

EDIT_AUTOSTART,
EDIT_BOOTORDER,
EDIT_BOOTMENU,
EDIT_KERNEL,
EDIT_INIT,

EDIT_DISK_RO,
EDIT_DISK_SHARE,
EDIT_DISK_REMOVABLE,
EDIT_DISK_CACHE,
EDIT_DISK_IO,
EDIT_DISK_BUS,
EDIT_DISK_SERIAL,
EDIT_DISK_FORMAT,
EDIT_DISK_IOTUNE,

EDIT_SOUND_MODEL,

EDIT_SMARTCARD_MODE,

EDIT_NET_MODEL,
EDIT_NET_VPORT,
EDIT_NET_SOURCE,

EDIT_GFX_PASSWD,
EDIT_GFX_USE_PASSWD,
EDIT_GFX_TYPE,
EDIT_GFX_KEYMAP,

EDIT_VIDEO_MODEL,

EDIT_WATCHDOG_MODEL,
EDIT_WATCHDOG_ACTION,

EDIT_CONTROLLER_MODEL,

EDIT_TPM_TYPE,

EDIT_FS,
) = range(1, 39)


# Columns in hw list model
(HW_LIST_COL_LABEL,
 HW_LIST_COL_ICON_NAME,
 HW_LIST_COL_ICON_SIZE,
 HW_LIST_COL_TYPE,
 HW_LIST_COL_DEVICE) = range(5)

# Types for the hw list model: numbers specify what order they will be listed
(HW_LIST_TYPE_GENERAL,
 HW_LIST_TYPE_INSPECTION,
 HW_LIST_TYPE_STATS,
 HW_LIST_TYPE_CPU,
 HW_LIST_TYPE_MEMORY,
 HW_LIST_TYPE_BOOT,
 HW_LIST_TYPE_DISK,
 HW_LIST_TYPE_NIC,
 HW_LIST_TYPE_INPUT,
 HW_LIST_TYPE_GRAPHICS,
 HW_LIST_TYPE_SOUND,
 HW_LIST_TYPE_CHAR,
 HW_LIST_TYPE_HOSTDEV,
 HW_LIST_TYPE_VIDEO,
 HW_LIST_TYPE_WATCHDOG,
 HW_LIST_TYPE_CONTROLLER,
 HW_LIST_TYPE_FILESYSTEM,
 HW_LIST_TYPE_SMARTCARD,
 HW_LIST_TYPE_REDIRDEV,
 HW_LIST_TYPE_TPM,
 HW_LIST_TYPE_RNG,
 HW_LIST_TYPE_PANIC) = range(22)

remove_pages = [HW_LIST_TYPE_NIC, HW_LIST_TYPE_INPUT,
                HW_LIST_TYPE_GRAPHICS, HW_LIST_TYPE_SOUND, HW_LIST_TYPE_CHAR,
                HW_LIST_TYPE_HOSTDEV, HW_LIST_TYPE_DISK, HW_LIST_TYPE_VIDEO,
                HW_LIST_TYPE_WATCHDOG, HW_LIST_TYPE_CONTROLLER,
                HW_LIST_TYPE_FILESYSTEM, HW_LIST_TYPE_SMARTCARD,
                HW_LIST_TYPE_REDIRDEV, HW_LIST_TYPE_TPM,
                HW_LIST_TYPE_RNG, HW_LIST_TYPE_PANIC]

# Boot device columns
(BOOT_DEV_TYPE,
 BOOT_LABEL,
 BOOT_ICON,
 BOOT_ACTIVE) = range(4)

# Main tab pages
(DETAILS_PAGE_DETAILS,
 DETAILS_PAGE_CONSOLE,
 DETAILS_PAGE_SNAPSHOTS) = range(3)


def prettyify_disk_bus(bus):
    if bus in ["ide", "sata", "scsi", "usb", "sd"]:
        return bus.upper()

    if bus in ["xen"]:
        return bus.capitalize()

    if bus == "virtio":
        return "VirtIO"

    if bus == "spapr-vscsi":
        return "vSCSI"

    return bus


def prettyify_disk(devtype, bus, idx):
    busstr = prettyify_disk_bus(bus) or ""

    if devtype == "floppy":
        devstr = "Floppy"
        busstr = ""
    elif devtype == "cdrom":
        devstr = "CDROM"
    else:
        devstr = devtype.capitalize()

    if busstr:
        ret = "%s %s" % (busstr, devstr)
    else:
        ret = devstr

    return "%s %s" % (ret, idx)


def safeint(val, fmt="%.3d"):
    try:
        int(val)
    except:
        return str(val)
    return fmt % int(val)


def prettyify_bytes(val):
    if val > (1024 * 1024 * 1024):
        return "%2.2f GB" % (val / (1024.0 * 1024.0 * 1024.0))
    else:
        return "%2.2f MB" % (val / (1024.0 * 1024.0))


def build_redir_label(redirdev):
    # String shown in the devices details section
    addrlabel = ""
    # String shown in the VMs hardware list
    hwlabel = ""

    if redirdev.type == 'spicevmc':
        addrlabel = None
    elif redirdev.type == 'tcp':
        addrlabel += _("%s:%s") % (redirdev.host, redirdev.service)
    else:
        raise RuntimeError("unhandled redirection kind: %s" % redirdev.type)

    hwlabel = _("Redirected %s") % redirdev.bus.upper()

    return addrlabel, hwlabel


def build_hostdev_label(hostdev):
    # String shown in the devices details section
    srclabel = ""
    # String shown in the VMs hardware list
    hwlabel = ""

    typ = hostdev.type
    vendor = hostdev.vendor
    product = hostdev.product
    addrbus = hostdev.bus
    addrdev = hostdev.device
    addrslt = hostdev.slot
    addrfun = hostdev.function
    addrdom = hostdev.domain

    def dehex(val):
        if val.startswith("0x"):
            val = val[2:]
        return val

    hwlabel = typ.upper()
    srclabel = typ.upper()

    if vendor and product:
        # USB by vendor + product
        devstr = " %s:%s" % (dehex(vendor), dehex(product))
        srclabel += devstr
        hwlabel += devstr

    elif addrbus and addrdev:
        # USB by bus + dev
        srclabel += (" Bus %s Device %s" %
                     (safeint(addrbus), safeint(addrdev)))
        hwlabel += " %s:%s" % (safeint(addrbus), safeint(addrdev))

    elif addrbus and addrslt and addrfun and addrdom:
        # PCI by bus:slot:function
        devstr = (" %s:%s:%s.%s" %
                  (dehex(addrdom), dehex(addrbus),
                   dehex(addrslt), dehex(addrfun)))
        srclabel += devstr
        hwlabel += devstr

    return srclabel, hwlabel


def lookup_nodedev(vmmconn, hostdev):
    def intify(val, do_hex=False):
        try:
            if do_hex:
                return int(val or '0x00', 16)
            else:
                return int(val)
        except:
            return -1

    def attrVal(node, attr):
        if not hasattr(node, attr):
            return None
        return getattr(node, attr)

    devtype = hostdev.type
    found_dev = None

    vendor_id = product_id = bus = device = domain = slot = func = None

    # For USB we want a device, not a bus
    if devtype == 'usb':
        devtype    = 'usb_device'
        vendor_id  = hostdev.vendor or -1
        product_id = hostdev.product or -1
        bus        = intify(hostdev.bus)
        device     = intify(hostdev.device)

    elif devtype == 'pci':
        domain     = intify(hostdev.domain, True)
        bus        = intify(hostdev.bus, True)
        slot       = intify(hostdev.slot, True)
        func       = intify(hostdev.function, True)

    devs = vmmconn.get_nodedevs(devtype, None)
    for dev in devs:
        # Try to match with product_id|vendor_id|bus|device
        if ((attrVal(dev, "product_id") == product_id or product_id == -1) and
            (attrVal(dev, "vendor_id") == vendor_id or vendor_id == -1) and
            (attrVal(dev, "bus") == bus or bus == -1) and
            (attrVal(dev, "device") == device or device == -1)):
            found_dev = dev
        else:
            # Try to get info from bus/addr
            dev_id = intify(attrVal(dev, "device"))
            bus_id = intify(attrVal(dev, "bus"))
            dom_id = intify(attrVal(dev, "domain"))
            func_id = intify(attrVal(dev, "function"))
            slot_id = intify(attrVal(dev, "slot"))

            if ((dev_id == device and bus_id == bus) or
                (dom_id == domain and func_id == func and
                 bus_id == bus and slot_id == slot)):
                found_dev = dev

        if found_dev:
            break

    return found_dev


class vmmDetails(vmmGObjectUI):
    __gsignals__ = {
        "action-save-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-destroy-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-suspend-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-resume-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-run-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-shutdown-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-reset-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-reboot-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-exit-app": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-view-manager": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-migrate-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-delete-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "action-clone-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "details-closed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "details-opened": (GObject.SignalFlags.RUN_FIRST, None, []),
        "customize-finished": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, vm, parent=None):
        vmmGObjectUI.__init__(self, "details.ui", "vmm-details")
        self.vm = vm
        self.conn = self.vm.conn

        self.is_customize_dialog = False
        if parent:
            # Details window is being abused as a 'configure before install'
            # dialog, set things as appropriate
            self.is_customize_dialog = True
            self.topwin.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            self.topwin.set_transient_for(parent)

            self.widget("toolbar-box").show()
            self.widget("customize-toolbar").show()
            self.widget("details-toolbar").hide()
            self.widget("details-menubar").hide()
            pages = self.widget("details-pages")
            pages.set_current_page(DETAILS_PAGE_DETAILS)


        self.active_edits = []

        self.addhw = None
        self.media_choosers = {"cdrom": None, "floppy": None}
        self.storage_browser = None

        self.ignorePause = False
        self.ignoreDetails = False
        self._cpu_copy_host = False

        from virtManager.console import vmmConsolePages
        self.console = vmmConsolePages(self.vm, self.builder, self.topwin)
        self.snapshots = vmmSnapshotPage(self.vm, self.builder, self.topwin)
        self.widget("snapshot-placeholder").add(self.snapshots.top_box)

        # Set default window size
        w, h = self.vm.get_details_window_size()
        self.topwin.set_default_size(w or 800, h or 600)

        self.oldhwkey = None
        self.addhwmenu = None
        self.keycombo_menu = None
        self.init_menus()
        self.init_details()

        self.cpu_usage_graph = None
        self.memory_usage_graph = None
        self.disk_io_graph = None
        self.network_traffic_graph = None
        self.init_graphs()

        self.builder.connect_signals({
            "on_close_details_clicked": self.close,
            "on_details_menu_close_activate": self.close,
            "on_vmm_details_delete_event": self.close,
            "on_vmm_details_configure_event": self.window_resized,
            "on_details_menu_quit_activate": self.exit_app,
            "on_hw_list_changed": self.hw_changed,
            "on_config_boot_list_changed": self.config_bootdev_selected,

            "on_control_vm_details_toggled": self.details_console_changed,
            "on_control_vm_console_toggled": self.details_console_changed,
            "on_control_snapshots_toggled": self.details_console_changed,
            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,
            "on_control_fullscreen_toggled": self.control_fullscreen,

            "on_details_customize_finish_clicked": self.customize_finish,
            "on_details_cancel_customize_clicked": self.close,

            "on_details_menu_virtual_manager_activate": self.control_vm_menu,
            "on_details_menu_run_activate": self.control_vm_run,
            "on_details_menu_poweroff_activate": self.control_vm_shutdown,
            "on_details_menu_reboot_activate": self.control_vm_reboot,
            "on_details_menu_save_activate": self.control_vm_save,
            "on_details_menu_reset_activate": self.control_vm_reset,
            "on_details_menu_destroy_activate": self.control_vm_destroy,
            "on_details_menu_pause_activate": self.control_vm_pause,
            "on_details_menu_clone_activate": self.control_vm_clone,
            "on_details_menu_migrate_activate": self.control_vm_migrate,
            "on_details_menu_delete_activate": self.control_vm_delete,
            "on_details_menu_screenshot_activate": self.control_vm_screenshot,
            "on_details_menu_usb_redirection": self.control_vm_usb_redirection,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,
            "on_details_menu_view_details_toggled": self.details_console_changed,
            "on_details_menu_view_console_toggled": self.details_console_changed,
            "on_details_menu_view_snapshots_toggled": self.details_console_changed,

            "on_details_pages_switch_page": self.switch_page,

            "on_overview_name_changed": lambda *x: self.enable_apply(x, EDIT_NAME),
            "on_overview_title_changed": lambda *x: self.enable_apply(x, EDIT_TITLE),
            "on_machine_type_changed": lambda *x: self.enable_apply(x, EDIT_MACHTYPE),

            "on_config_vcpus_changed": self.config_vcpus_changed,
            "on_config_maxvcpus_changed": self.config_maxvcpus_changed,
            "on_config_vcpupin_changed": lambda *x: self.enable_apply(x, EDIT_CPUSET),
            "on_config_vcpupin_generate_clicked": self.config_vcpupin_generate,
            "on_cpu_model_changed": lambda *x: self.enable_apply(x, EDIT_CPU),
            "on_cpu_cores_changed": lambda *x: self.enable_apply(x, EDIT_TOPOLOGY),
            "on_cpu_sockets_changed": lambda *x: self.enable_apply(x, EDIT_TOPOLOGY),
            "on_cpu_threads_changed": lambda *x: self.enable_apply(x, EDIT_TOPOLOGY),
            "on_cpu_copy_host_clicked": self.config_cpu_copy_host,
            "on_cpu_clear_clicked": self.config_cpu_clear,
            "on_cpu_topology_enable_toggled": self.config_cpu_topology_enable,

            "on_config_memory_changed": self.config_memory_changed,
            "on_config_maxmem_changed": self.config_maxmem_changed,


            "on_config_boot_moveup_clicked" : lambda *x: self.config_boot_move(x, True),
            "on_config_boot_movedown_clicked" : lambda *x: self.config_boot_move(x, False),
            "on_config_autostart_changed": lambda *x: self.enable_apply(x, x, EDIT_AUTOSTART),
            "on_boot_menu_changed": lambda *x: self.enable_apply(x, EDIT_BOOTMENU),
            "on_boot_kernel_enable_toggled": self.boot_kernel_toggled,
            "on_boot_kernel_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_initrd_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_dtb_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_kernel_args_changed": lambda *x: self.enable_apply(x, EDIT_KERNEL),
            "on_boot_kernel_browse_clicked": self.browse_kernel,
            "on_boot_initrd_browse_clicked": self.browse_initrd,
            "on_boot_dtb_browse_clicked": self.browse_dtb,
            "on_boot_init_path_changed": lambda *x: self.enable_apply(x, EDIT_INIT),

            "on_disk_readonly_changed": lambda *x: self.enable_apply(x, EDIT_DISK_RO),
            "on_disk_shareable_changed": lambda *x: self.enable_apply(x, EDIT_DISK_SHARE),
            "on_disk_removable_changed": lambda *x: self.enable_apply(x, EDIT_DISK_REMOVABLE),
            "on_disk_cache_combo_changed": lambda *x: self.enable_apply(x, EDIT_DISK_CACHE),
            "on_disk_io_combo_changed": lambda *x: self.enable_apply(x, EDIT_DISK_IO),
            "on_disk_bus_combo_changed": lambda *x: self.enable_apply(x, EDIT_DISK_BUS),
            "on_disk_format_changed": lambda *x: self.enable_apply(x, EDIT_DISK_FORMAT),
            "on_disk_serial_changed": lambda *x: self.enable_apply(x, EDIT_DISK_SERIAL),
            "on_disk_iotune_changed": self.iotune_changed,

            "on_network_source_combo_changed": lambda *x: self.enable_apply(x, EDIT_NET_SOURCE),
            "on_network_bridge_changed": lambda *x: self.enable_apply(x, EDIT_NET_SOURCE),
            "on_network-source-mode-combo_changed": lambda *x: self.enable_apply(x, EDIT_NET_SOURCE),
            "on_network_model_combo_changed": lambda *x: self.enable_apply(x, EDIT_NET_MODEL),

            "on_vport_type_changed": lambda *x: self.enable_apply(x, EDIT_NET_VPORT),
            "on_vport_managerid_changed": lambda *x: self.enable_apply(x,
                                           EDIT_NET_VPORT),
            "on_vport_typeid_changed": lambda *x: self.enable_apply(x,
                                        EDIT_NET_VPORT),
            "on_vport_typeidversion_changed": lambda *x: self.enable_apply(x,
                                               EDIT_NET_VPORT),
            "on_vport_instanceid_changed": lambda *x: self.enable_apply(x,
                                            EDIT_NET_VPORT),

            "on_gfx_type_combo_changed": lambda *x: self.enable_apply(x, EDIT_GFX_TYPE),
            "on_vnc_keymap_combo_changed": lambda *x: self.enable_apply(x,
                                            EDIT_GFX_KEYMAP),

            "on_vnc_use_password_toggled": lambda *x: self.control_gfx_use_passwd(x),
            "on_vnc_password_changed": lambda *x: self.enable_apply(x, EDIT_GFX_PASSWD),

            "on_sound_model_combo_changed": lambda *x: self.enable_apply(x,
                                             EDIT_SOUND_MODEL),

            "on_video_model_combo_changed": lambda *x: self.enable_apply(x,
                                             EDIT_VIDEO_MODEL),

            "on_watchdog_model_combo_changed": lambda *x: self.enable_apply(x,
                                                EDIT_WATCHDOG_MODEL),
            "on_watchdog_action_combo_changed": lambda *x: self.enable_apply(x,
                                                 EDIT_WATCHDOG_ACTION),

            "on_smartcard_mode_combo_changed": lambda *x: self.enable_apply(x,
                                                EDIT_SMARTCARD_MODE),

            "on_config_apply_clicked": self.config_apply,
            "on_config_cancel_clicked": self.config_cancel,

            "on_config_cdrom_connect_clicked": self.toggle_storage_media,
            "on_config_remove_clicked": self.remove_xml_dev,
            "on_add_hardware_button_clicked": self.add_hardware,

            "on_hw_list_button_press_event": self.popup_addhw_menu,

            # Listeners stored in vmmConsolePages
            "on_details_menu_view_fullscreen_activate": self.console.toggle_fullscreen,
            "on_details_menu_view_size_to_vm_activate": self.console.size_to_vm,
            "on_details_menu_view_scale_always_toggled": self.console.set_scale_type,
            "on_details_menu_view_scale_fullscreen_toggled": self.console.set_scale_type,
            "on_details_menu_view_scale_never_toggled": self.console.set_scale_type,

            "on_console_pages_switch_page": self.console.page_changed,
            "on_console_auth_password_activate": self.console.auth_login,
            "on_console_auth_login_clicked": self.console.auth_login,
            "on_controller_model_combo_changed": lambda *x: self.enable_apply(x,
                                                  EDIT_CONTROLLER_MODEL),
        })

        # Deliberately keep all this after signal connection
        self.vm.connect("status-changed", self.refresh_vm_state)
        self.vm.connect("config-changed", self.refresh_vm_state)
        self.vm.connect("resources-sampled", self.refresh_resources)

        self.fsDetails = vmmFSDetails(self.vm)
        self.fsDetails.set_initial_state()
        fsAlignment = self.widget("fs-alignment")
        fsAlignment.add(self.fsDetails.topwin)
        self.fsDetails.connect("changed", lambda *x: self.enable_apply(x,
                                           EDIT_FS))

        self.populate_hw_list()
        self.repopulate_boot_list()

        self.hw_selected()
        self.refresh_vm_state()

    def _cleanup(self):
        self.oldhwkey = None

        if self.addhw:
            self.addhw.cleanup()
            self.addhw = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

        for key in self.media_choosers:
            if self.media_choosers[key]:
                self.media_choosers[key].cleanup()
        self.media_choosers = {}

        self.console.cleanup()
        self.console = None
        self.snapshots.cleanup()
        self.snapshots = None

        self.vm = None
        self.conn = None
        self.addhwmenu = None

        self.fsDetails.cleanup()

    def show(self):
        logging.debug("Showing VM details: %s", self.vm)
        vis = self.is_visible()
        self.topwin.present()
        if vis:
            return

        self.fsDetails.topwin.show_all()

        self.emit("details-opened")
        self.refresh_vm_state()

    def customize_finish(self, src):
        ignore = src
        if self.has_unapplied_changes(self.get_hw_row()):
            return

        return self._close(customize_finish=True)

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing VM details: %s", self.vm)
        return self._close()

    def _close(self, customize_finish=False):
        fs = self.widget("details-menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)

        if not self.is_visible():
            return

        self.topwin.hide()
        if (self.console.viewer and
            self.console.viewer.display and
            self.console.viewer.display.get_visible()):
            try:
                self.console.close_viewer()
            except:
                logging.error("Failure when disconnecting from desktop server")

        if customize_finish:
            self.emit("customize-finished")
        else:
            self.emit("details-closed")
        return 1

    def is_visible(self):
        return bool(self.topwin.get_visible())


    ##########################
    # Initialization helpers #
    ##########################

    def init_menus(self):
        # Virtual Machine menu
        menu = sharedui.VMShutdownMenu(self, lambda: self.vm)
        self.widget("control-shutdown").set_menu(menu)
        self.widget("control-shutdown").set_icon_name("system-shutdown")

        topmenu = self.widget("details-vm-menu")
        submenu = topmenu.get_submenu()
        newmenu = sharedui.VMActionMenu(self, lambda: self.vm,
                                        show_open=False)
        for child in submenu.get_children():
            submenu.remove(child)
            newmenu.add(child)  # pylint: disable=E1101
        topmenu.set_submenu(newmenu)
        topmenu.show_all()

        # Add HW popup menu
        self.addhwmenu = Gtk.Menu()

        addHW = Gtk.ImageMenuItem(_("_Add Hardware"))
        addHW.set_use_underline(True)
        addHWImg = Gtk.Image()
        addHWImg.set_from_stock(Gtk.STOCK_ADD, Gtk.IconSize.MENU)
        addHW.set_image(addHWImg)
        addHW.show()
        addHW.connect("activate", self.add_hardware)

        rmHW = Gtk.ImageMenuItem(_("_Remove Hardware"))
        rmHW.set_use_underline(True)
        rmHWImg = Gtk.Image()
        rmHWImg.set_from_stock(Gtk.STOCK_REMOVE, Gtk.IconSize.MENU)
        rmHW.set_image(rmHWImg)
        rmHW.show()
        rmHW.connect("activate", self.remove_xml_dev)

        self.addhwmenu.add(addHW)
        self.addhwmenu.add(rmHW)

        # Don't allowing changing network/disks for Dom0
        dom0 = self.vm.is_management_domain()
        self.widget("add-hardware-button").set_sensitive(not dom0)

        self.widget("hw-panel").set_show_tabs(False)
        self.widget("details-pages").set_show_tabs(False)
        self.widget("console-pages").set_show_tabs(False)
        self.widget("details-menu-view-toolbar").set_active(
                                    self.config.get_details_show_toolbar())

        # Keycombo menu (ctrl+alt+del etc.)
        self.keycombo_menu = self.console.build_keycombo_menu(
            self.console.send_key)
        self.widget("details-menu-send-key").set_submenu(self.keycombo_menu)


    def init_graphs(self):
        def _make_graph():
            g = Sparkline()
            g.set_property("reversed", True)
            g.show()
            return g

        self.cpu_usage_graph = _make_graph()
        self.widget("overview-cpu-usage-align").add(self.cpu_usage_graph)

        self.memory_usage_graph = _make_graph()
        self.widget("overview-memory-usage-align").add(self.memory_usage_graph)

        self.disk_io_graph = _make_graph()
        self.disk_io_graph.set_property("filled", False)
        self.disk_io_graph.set_property("num_sets", 2)
        self.disk_io_graph.set_property("rgb", [x / 255.0 for x in
                                        [0x82, 0x00, 0x3B, 0x29, 0x5C, 0x45]])
        self.widget("overview-disk-usage-align").add(self.disk_io_graph)

        self.network_traffic_graph = _make_graph()
        self.network_traffic_graph.set_property("filled", False)
        self.network_traffic_graph.set_property("num_sets", 2)
        self.network_traffic_graph.set_property("rgb", [x / 255.0 for x in
                                                    [0x82, 0x00, 0x3B,
                                                     0x29, 0x5C, 0x45]])
        self.widget("overview-network-traffic-align").add(
            self.network_traffic_graph)

    def init_details(self):
        # Hardware list
        # [ label, icon name, icon size, hw type, hw data/class]
        hw_list_model = Gtk.ListStore(str, str, int, int, object)
        self.widget("hw-list").set_model(hw_list_model)

        hwCol = Gtk.TreeViewColumn("Hardware")
        hwCol.set_spacing(6)
        hwCol.set_min_width(165)
        hw_txt = Gtk.CellRendererText()
        hw_img = Gtk.CellRendererPixbuf()
        hwCol.pack_start(hw_img, False)
        hwCol.pack_start(hw_txt, True)
        hwCol.add_attribute(hw_txt, 'text', HW_LIST_COL_LABEL)
        hwCol.add_attribute(hw_img, 'stock-size', HW_LIST_COL_ICON_SIZE)
        hwCol.add_attribute(hw_img, 'icon-name', HW_LIST_COL_ICON_NAME)
        self.widget("hw-list").append_column(hwCol)

        # Description text view
        desc = self.widget("overview-description")
        buf = Gtk.TextBuffer()
        buf.connect("changed", self.enable_apply, EDIT_DESC)
        desc.set_buffer(buf)

        arch = self.vm.get_arch()
        caps = self.vm.conn.caps

        # Machine type
        machtype_combo = self.widget("machine-type")
        machtype_model = Gtk.ListStore(str)
        machtype_combo.set_model(machtype_model)
        text = Gtk.CellRendererText()
        machtype_combo.pack_start(text, True)
        machtype_combo.add_attribute(text, 'text', 0)
        machtype_model.set_sort_column_id(0, Gtk.SortType.ASCENDING)

        show_machine = (arch not in ["i686", "x86_64"])
        uiutil.set_grid_row_visible(self.widget("machine-type"),
                                       show_machine)

        if show_machine:
            machines = []

            try:
                ignore, domain = caps.guest_lookup(
                    os_type=self.vm.get_abi_type(),
                    arch=self.vm.get_arch(),
                    typ=self.vm.get_hv_type(),
                    machine=self.vm.get_machtype())

                machines = domain.machines[:]
            except:
                logging.exception("Error determining machine list")

            for machine in machines:
                if machine == "none":
                    continue
                machtype_model.append([machine])

        # Inspection page
        apps_list = self.widget("inspection-apps")
        apps_model = Gtk.ListStore(str, str, str)
        apps_list.set_model(apps_model)

        name_col = Gtk.TreeViewColumn(_("Name"))
        version_col = Gtk.TreeViewColumn(_("Version"))
        summary_col = Gtk.TreeViewColumn()

        apps_list.append_column(name_col)
        apps_list.append_column(version_col)
        apps_list.append_column(summary_col)

        name_text = Gtk.CellRendererText()
        name_col.pack_start(name_text, True)
        name_col.add_attribute(name_text, 'text', 0)
        name_col.set_sort_column_id(0)

        version_text = Gtk.CellRendererText()
        version_col.pack_start(version_text, True)
        version_col.add_attribute(version_text, 'text', 1)
        version_col.set_sort_column_id(1)

        summary_text = Gtk.CellRendererText()
        summary_col.pack_start(summary_text, True)
        summary_col.add_attribute(summary_text, 'text', 2)
        summary_col.set_sort_column_id(2)


        # VCPU Pinning list
        generate_cpuset = self.widget("config-vcpupin-generate")
        generate_warn = self.widget("config-vcpupin-generate-err")
        if not self.conn.caps.host.topology:
            generate_cpuset.set_sensitive(False)
            generate_warn.show()
            generate_warn.set_tooltip_text(
                _("Libvirt did not detect NUMA capabilities."))


        # Boot device list
        boot_list = self.widget("config-boot-list")
        # model = [ XML boot type, display name, icon name, enabled ]
        boot_list_model = Gtk.ListStore(str, str, str, bool)
        boot_list.set_model(boot_list_model)

        chkCol = Gtk.TreeViewColumn()
        txtCol = Gtk.TreeViewColumn()

        boot_list.append_column(chkCol)
        boot_list.append_column(txtCol)

        chk = Gtk.CellRendererToggle()
        chk.connect("toggled", self.config_boot_toggled)
        chkCol.pack_start(chk, False)
        chkCol.add_attribute(chk, 'active', BOOT_ACTIVE)

        icon = Gtk.CellRendererPixbuf()
        txtCol.pack_start(icon, False)
        txtCol.add_attribute(icon, 'icon-name', BOOT_ICON)

        text = Gtk.CellRendererText()
        txtCol.pack_start(text, True)
        txtCol.add_attribute(text, 'text', BOOT_LABEL)
        txtCol.add_attribute(text, 'sensitive', BOOT_ACTIVE)

        no_default = not self.is_customize_dialog

        # CPU features
        caps = self.vm.conn.caps
        cpu_values = None
        cpu_names = []
        all_features = []

        try:
            cpu_values = caps.get_cpu_values(self.vm.get_arch())
            cpu_names = sorted([c.model for c in cpu_values.cpus],
                               key=str.lower)
            all_features = cpu_values.features
        except:
            logging.exception("Error populating CPU model list")

        # [ feature name, mode]
        feat_list = self.widget("cpu-features")
        feat_model = Gtk.ListStore(str, str)
        feat_list.set_model(feat_model)

        nameCol = Gtk.TreeViewColumn()
        polCol = Gtk.TreeViewColumn()
        polCol.set_min_width(80)

        feat_list.append_column(nameCol)
        feat_list.append_column(polCol)

        # Feature name col
        name_text = Gtk.CellRendererText()
        nameCol.pack_start(name_text, True)
        nameCol.add_attribute(name_text, 'text', 0)
        nameCol.set_sort_column_id(0)

        # Feature policy col
        feat_combo = Gtk.CellRendererCombo()
        m = Gtk.ListStore(str)
        for p in virtinst.CPUFeature.POLICIES:
            m.append([p])
        m.append(["default"])
        feat_combo.set_property("model", m)
        feat_combo.set_property("text-column", 0)
        feat_combo.set_property("editable", True)
        polCol.pack_start(feat_combo, False)
        polCol.add_attribute(feat_combo, 'text', 1)
        polCol.set_sort_column_id(1)

        def feature_changed(src, index, treeiter, model):
            model[index][1] = src.get_property("model")[treeiter][0]
            self.enable_apply(EDIT_CPU)

        feat_combo.connect("changed", feature_changed, feat_model)
        for name in all_features:
            feat_model.append([name, "default"])

        # CPU model combo
        cpu_model = self.widget("cpu-model")

        model = Gtk.ListStore(str, object)
        cpu_model.set_model(model)
        cpu_model.set_entry_text_column(0)
        model.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        for name in cpu_names:
            model.append([name, cpu_values.get_cpu(name)])

        # Disk cache combo
        disk_cache = self.widget("disk-cache")
        vmmAddHardware.build_disk_cache_combo(self.vm, disk_cache)

        # Disk io combo
        disk_io = self.widget("disk-io")
        vmmAddHardware.build_disk_io_combo(self.vm, disk_io)

        # Disk format combo
        format_list = self.widget("disk-format")
        vmmAddHardware.populate_disk_format_combo(self.vm, format_list, False)

        # Disk bus combo
        disk_bus = self.widget("disk-bus")
        vmmAddHardware.build_disk_bus_combo(self.vm, disk_bus)

        # Disk iotune expander
        if not (self.conn.is_qemu() or self.conn.is_test_conn()):
            self.widget("iotune-expander").set_visible(False)

        # Network source
        net_source = self.widget("network-source")
        net_bridge = self.widget("network-bridge-box")
        source_mode_combo = self.widget("network-source-mode")
        vport_expander = self.widget("vport-expander")
        sharedui.build_network_list(net_source, net_bridge,
                                    source_mode_combo, vport_expander)

        # source mode
        source_mode = self.widget("network-source-mode")
        vmmAddHardware.build_network_source_mode_combo(self.vm, source_mode)

        # Network model
        net_model = self.widget("network-model")
        vmmAddHardware.build_network_model_combo(self.vm, net_model)

        # Graphics type
        gfx_type = self.widget("gfx-type")
        model = Gtk.ListStore(str, str)
        gfx_type.set_model(model)
        uiutil.set_combo_text_column(gfx_type, 1)
        model.append([virtinst.VirtualGraphics.TYPE_VNC, "VNC"])
        model.append([virtinst.VirtualGraphics.TYPE_SPICE, "Spice"])
        gfx_type.set_active(-1)

        # Graphics keymap
        gfx_keymap = self.widget("gfx-keymap")
        vmmAddHardware.build_graphics_keymap_combo(self.vm, gfx_keymap,
                                         no_default=no_default)

        # Sound model
        sound_dev = self.widget("sound-model")
        vmmAddHardware.build_sound_combo(self.vm, sound_dev,
            no_default=no_default)

        # Video model combo
        video_dev = self.widget("video-model")
        vmmAddHardware.build_video_combo(self.vm, video_dev,
            no_default=no_default)

        # Watchdog model combo
        combo = self.widget("watchdog-model")
        vmmAddHardware.build_watchdogmodel_combo(self.vm, combo,
                                            no_default=no_default)

        # Watchdog action combo
        combo = self.widget("watchdog-action")
        vmmAddHardware.build_watchdogaction_combo(self.vm, combo,
                                             no_default=no_default)

        # Smartcard mode
        sc_mode = self.widget("smartcard-mode")
        vmmAddHardware.build_smartcard_mode_combo(self.vm, sc_mode)

        # Controller model
        combo = self.widget("controller-model")
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)
        combo.set_active(-1)


    def set_combo_entry(self, widget, value, label="", comparefunc=None):
        label = label or value
        model_combo = self.widget(widget)

        idx = -1
        if comparefunc:
            model_in_list, idx = comparefunc(model_combo.get_model(), value)
        else:
            model_list = [x[0] for x in model_combo.get_model()]
            model_in_list = (value in model_list)
            if model_in_list:
                idx = model_list.index(value)

        model_combo.set_active(idx)
        if idx == -1 and model_combo.get_has_entry():
            model_combo.get_child().set_text(value or "")

    def get_combo_entry(self, widgetname):
        combo = self.widget(widgetname)
        if combo.get_active() >= 0:
            return combo.get_model()[combo.get_active()][0]
        if not combo.get_has_entry():
            return None
        return combo.get_child().get_text().strip()


    ##########################
    # Window state listeners #
    ##########################

    def window_resized(self, ignore, event):
        # Sometimes dimensions change when window isn't visible
        if not self.is_visible():
            return

        self.vm.set_details_window_size(event.width, event.height)

    def popup_addhw_menu(self, widget, event):
        ignore = widget
        if event.button != 3:
            return

        self.addhwmenu.popup(None, None, None, None, 0, event.time)

    def control_fullscreen(self, src):
        menu = self.widget("details-menu-view-fullscreen")
        if src.get_active() != menu.get_active():
            menu.set_active(src.get_active())

    def toggle_toolbar(self, src):
        if self.is_customize_dialog:
            return

        active = src.get_active()
        self.config.set_details_show_toolbar(active)

        if (active and not
            self.widget("details-menu-view-fullscreen").get_active()):
            self.widget("toolbar-box").show()
        else:
            self.widget("toolbar-box").hide()

    def get_selected_row(self, widget):
        selection = widget.get_selection()
        model, treepath = selection.get_selected()
        if treepath is None:
            return None
        return model[treepath]

    def get_boot_selection(self):
        return self.get_selected_row(self.widget("config-boot-list"))

    def set_hw_selection(self, page, disable_apply=True):
        if disable_apply:
            self.disable_apply()

        hwlist = self.widget("hw-list")
        selection = hwlist.get_selection()
        selection.select_path(str(page))

    def get_hw_row(self):
        return self.get_selected_row(self.widget("hw-list"))

    def get_hw_selection(self, field):
        row = self.get_hw_row()
        if not row:
            return None
        return row[field]

    def force_get_hw_pagetype(self, page=None):
        if page:
            return page

        page = self.get_hw_selection(HW_LIST_COL_TYPE)
        if page is None:
            page = HW_LIST_TYPE_GENERAL
            self.set_hw_selection(0)

        return page

    def has_unapplied_changes(self, row):
        if not row:
            return False

        if not self.widget("config-apply").get_sensitive():
            return False

        if not self.err.chkbox_helper(
            self.config.get_confirm_unapplied,
            self.config.set_confirm_unapplied,
            text1=(_("There are unapplied changes. Would you like to apply "
                     "them now?")),
            chktext=_("Don't warn me again."),
            alwaysrecord=True,
            default=False):
            return False

        return not self.config_apply(row=row)

    def hw_changed(self, ignore):
        newrow = self.get_hw_row()
        model = self.widget("hw-list").get_model()

        if not newrow or newrow[HW_LIST_COL_DEVICE] == self.oldhwkey:
            return

        oldhwrow = None
        for row in model:
            if row[HW_LIST_COL_DEVICE] == self.oldhwkey:
                oldhwrow = row
                break

        if self.has_unapplied_changes(oldhwrow):
            # Unapplied changes, and syncing them failed
            pageidx = 0
            for idx in range(len(model)):
                if model[idx][HW_LIST_COL_DEVICE] == self.oldhwkey:
                    pageidx = idx
                    break
            self.set_hw_selection(pageidx, disable_apply=False)
        else:
            self.oldhwkey = newrow[HW_LIST_COL_DEVICE]
            self.hw_selected()

    def hw_selected(self, page=None):
        pagetype = self.force_get_hw_pagetype(page)

        self.widget("config-remove").set_sensitive(True)
        self.widget("hw-panel").set_sensitive(True)
        self.widget("hw-panel").show()

        try:
            if pagetype == HW_LIST_TYPE_GENERAL:
                self.refresh_overview_page()
            elif pagetype == HW_LIST_TYPE_INSPECTION:
                self.refresh_inspection_page()
            elif pagetype == HW_LIST_TYPE_STATS:
                self.refresh_stats_page()
            elif pagetype == HW_LIST_TYPE_CPU:
                self.refresh_config_cpu()
            elif pagetype == HW_LIST_TYPE_MEMORY:
                self.refresh_config_memory()
            elif pagetype == HW_LIST_TYPE_BOOT:
                self.refresh_boot_page()
            elif pagetype == HW_LIST_TYPE_DISK:
                self.refresh_disk_page()
            elif pagetype == HW_LIST_TYPE_NIC:
                self.refresh_network_page()
            elif pagetype == HW_LIST_TYPE_INPUT:
                self.refresh_input_page()
            elif pagetype == HW_LIST_TYPE_GRAPHICS:
                self.refresh_graphics_page()
            elif pagetype == HW_LIST_TYPE_SOUND:
                self.refresh_sound_page()
            elif pagetype == HW_LIST_TYPE_CHAR:
                self.refresh_char_page()
            elif pagetype == HW_LIST_TYPE_HOSTDEV:
                self.refresh_hostdev_page()
            elif pagetype == HW_LIST_TYPE_VIDEO:
                self.refresh_video_page()
            elif pagetype == HW_LIST_TYPE_WATCHDOG:
                self.refresh_watchdog_page()
            elif pagetype == HW_LIST_TYPE_CONTROLLER:
                self.refresh_controller_page()
            elif pagetype == HW_LIST_TYPE_FILESYSTEM:
                self.refresh_filesystem_page()
            elif pagetype == HW_LIST_TYPE_SMARTCARD:
                self.refresh_smartcard_page()
            elif pagetype == HW_LIST_TYPE_REDIRDEV:
                self.refresh_redir_page()
            elif pagetype == HW_LIST_TYPE_TPM:
                self.refresh_tpm_page()
            elif pagetype == HW_LIST_TYPE_RNG:
                self.refresh_rng_page()
            elif pagetype == HW_LIST_TYPE_PANIC:
                self.refresh_panic_page()
            else:
                pagetype = -1
        except Exception, e:
            self.err.show_err(_("Error refreshing hardware page: %s") % str(e))
            # Don't return, we want the rest of the bits to run regardless

        self.disable_apply()
        rem = pagetype in remove_pages
        self.widget("config-remove").set_visible(rem)

        self.widget("hw-panel").set_current_page(pagetype)

    def details_console_changed(self, src):
        if self.ignoreDetails:
            return

        if not src.get_active():
            return

        is_details = (src == self.widget("control-vm-details") or
                      src == self.widget("details-menu-view-details"))
        is_snapshot = (src == self.widget("control-snapshots") or
                       src == self.widget("details-menu-view-snapshots"))

        pages = self.widget("details-pages")
        if pages.get_current_page() == DETAILS_PAGE_DETAILS:
            if self.has_unapplied_changes(self.get_hw_row()):
                self.sync_details_console_view(True)
                return
            self.disable_apply()

        if is_details:
            pages.set_current_page(DETAILS_PAGE_DETAILS)
        elif is_snapshot:
            self.snapshots.show_page()
            pages.set_current_page(DETAILS_PAGE_SNAPSHOTS)
        else:
            pages.set_current_page(DETAILS_PAGE_CONSOLE)

    def sync_details_console_view(self, newpage):
        details = self.widget("control-vm-details")
        details_menu = self.widget("details-menu-view-details")
        console = self.widget("control-vm-console")
        console_menu = self.widget("details-menu-view-console")
        snapshot = self.widget("control-snapshots")
        snapshot_menu = self.widget("details-menu-view-snapshots")

        is_details = newpage == DETAILS_PAGE_DETAILS
        is_snapshot = newpage == DETAILS_PAGE_SNAPSHOTS
        is_console = not is_details and not is_snapshot

        try:
            self.ignoreDetails = True

            details.set_active(is_details)
            details_menu.set_active(is_details)
            snapshot.set_active(is_snapshot)
            snapshot_menu.set_active(is_snapshot)
            console.set_active(is_console)
            console_menu.set_active(is_console)
        finally:
            self.ignoreDetails = False

    def switch_page(self, ignore1=None, ignore2=None, newpage=None):
        self.page_refresh(newpage)

        self.sync_details_console_view(newpage)
        self.console.set_allow_fullscreen()

    def change_run_text(self, can_restore):
        if can_restore:
            text = _("_Restore")
        else:
            text = _("_Run")
        strip_text = text.replace("_", "")

        self.widget("details-vm-menu").get_submenu().change_run_text(text)
        self.widget("control-run").set_label(strip_text)

    def refresh_vm_state(self, ignore1=None, ignore2=None, ignore3=None):
        vm = self.vm
        status = self.vm.status()

        self.widget("details-menu-view-toolbar").set_active(
            self.config.get_details_show_toolbar())
        self.toggle_toolbar(self.widget("details-menu-view-toolbar"))

        active = vm.is_active()
        run = vm.is_runable()
        stop = vm.is_stoppable()
        paused = vm.is_paused()
        ro = vm.is_read_only()

        if vm.managedsave_supported:
            self.change_run_text(vm.hasSavedImage())

        self.widget("control-run").set_sensitive(run)
        self.widget("control-shutdown").set_sensitive(stop)
        self.widget("control-shutdown").get_menu().update_widget_states(vm)
        self.widget("control-pause").set_sensitive(stop)

        self.widget("details-vm-menu").get_submenu().update_widget_states(vm)
        self.set_pause_state(paused)

        self.widget("overview-name").set_editable(not active)

        self.widget("config-vcpus").set_sensitive(not ro)
        self.widget("config-vcpupin").set_sensitive(not ro)
        self.widget("config-memory").set_sensitive(not ro)
        self.widget("config-maxmem").set_sensitive(not ro)

        # Disable send key menu entries for offline VM
        self.console.send_key_button.set_sensitive(not (run or paused))
        send_key = self.widget("details-menu-send-key")
        for c in send_key.get_submenu().get_children():
            c.set_sensitive(not (run or paused))

        self.console.update_widget_states(vm, status)
        if not run:
            self.activate_default_console_page()

        self.widget("overview-status-text").set_text(self.vm.run_status())
        self.widget("overview-status-icon").set_from_icon_name(
                            self.vm.run_status_icon_name(), Gtk.IconSize.BUTTON)

        details = self.widget("details-pages")
        self.page_refresh(details.get_current_page())

        errmsg = self.vm.snapshots_supported()
        cansnap = not bool(errmsg)
        self.widget("control-snapshots").set_sensitive(cansnap)
        self.widget("details-menu-view-snapshots").set_sensitive(cansnap)
        tooltip = _("Manage VM snapshots")
        if not cansnap:
            tooltip += "\n" + errmsg
        self.widget("control-snapshots").set_tooltip_text(tooltip)


    #############################
    # External action listeners #
    #############################

    def view_manager(self, src_ignore):
        self.emit("action-view-manager")

    def exit_app(self, src_ignore):
        self.emit("action-exit-app")

    def activate_default_console_page(self):
        pages = self.widget("details-pages")
        if pages.get_current_page() != DETAILS_PAGE_CONSOLE:
            return
        self.console.activate_default_console_page()

    # activate_* are called from engine.py via CLI options
    def activate_default_page(self):
        pages = self.widget("details-pages")
        pages.set_current_page(DETAILS_PAGE_CONSOLE)
        self.activate_default_console_page()

    def activate_console_page(self):
        pages = self.widget("details-pages")
        pages.set_current_page(DETAILS_PAGE_CONSOLE)

    def activate_performance_page(self):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_DETAILS)
        self.set_hw_selection(HW_LIST_TYPE_STATS)

    def activate_config_page(self):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_DETAILS)

    def add_hardware(self, src_ignore):
        try:
            if self.addhw is None:
                self.addhw = vmmAddHardware(self.vm, self.is_customize_dialog)

            self.addhw.show(self.topwin)
        except Exception, e:
            self.err.show_err((_("Error launching hardware dialog: %s") %
                               str(e)))

    def remove_xml_dev(self, src_ignore):
        info = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not info:
            return

        devtype = info.virtual_device_type
        self.remove_device(devtype, info)

    def set_pause_state(self, paused):
        # Set pause widget states
        try:
            self.ignorePause = True
            self.widget("control-pause").set_property("active", paused)
        finally:
            self.ignorePause = False

    def control_vm_pause(self, src):
        if self.ignorePause:
            return

        # Let state handler listener change things if nec.
        self.set_pause_state(not src.get_active())

        if not self.vm.is_paused():
            self.emit("action-suspend-domain",
                      self.vm.conn.get_uri(),
                      self.vm.get_uuid())
        else:
            self.emit("action-resume-domain",
                      self.vm.conn.get_uri(),
                      self.vm.get_uuid())

    def control_vm_menu(self, src_ignore):
        can_usb = bool(self.console.viewer and
                       self.console.viewer.has_usb_redirection() and
                       self.vm.has_spicevmc_type_redirdev())
        self.widget("details-menu-usb-redirection").set_sensitive(can_usb)

    def control_gfx_use_passwd(self, x):
        passwd_widget = self.widget("gfx-password")
        sensitive = self.widget("gfx-use-password").get_active()
        if not sensitive:
            passwd_widget.set_text("")
        passwd_widget.set_sensitive(sensitive)
        self.enable_apply(x, EDIT_GFX_USE_PASSWD)

    def control_vm_run(self, src_ignore):
        self.emit("action-run-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_shutdown(self, src_ignore):
        self.emit("action-shutdown-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_reboot(self, src_ignore):
        self.emit("action-reboot-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_save(self, src_ignore):
        self.emit("action-save-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_reset(self, src_ignore):
        self.emit("action-reset-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_destroy(self, src_ignore):
        self.emit("action-destroy-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_clone(self, src_ignore):
        self.emit("action-clone-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_migrate(self, src_ignore):
        self.emit("action-migrate-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_delete(self, src_ignore):
        self.emit("action-delete-domain",
                  self.vm.conn.get_uri(), self.vm.get_uuid())

    def control_vm_screenshot(self, src):
        ignore = src
        try:
            return self._take_screenshot()
        except Exception, e:
            self.err.show_err(_("Error taking screenshot: %s") % str(e))

    def control_vm_usb_redirection(self, src):
        ignore = src
        spice_usbdev_dialog = self.err

        spice_usbdev_widget = self.console.viewer.get_usb_widget()
        if not spice_usbdev_widget:
            self.err.show_err(_("Error initializing spice USB device widget"))
            return

        spice_usbdev_widget.show()
        spice_usbdev_dialog.show_info(_("Select USB devices for redirection"),
                                      widget=spice_usbdev_widget)

    def _take_screenshot(self):
        image = self.console.viewer.get_pixbuf()

        metadata = {
            'tEXt::Hypervisor URI': self.vm.conn.get_uri(),
            'tEXt::Domain Name': self.vm.get_name(),
            'tEXt::Domain UUID': self.vm.get_uuid(),
            'tEXt::Generator App': self.config.get_appname(),
            'tEXt::Generator Version': self.config.get_appversion(),
        }

        ret = image.save_to_bufferv('png', metadata.keys(), metadata.values())
        # On Fedora 19, ret is (bool, str)
        # Someday the bindings might be fixed to just return the str, try
        # and future proof it a bit
        if type(ret) is tuple and len(ret) >= 2:
            ret = ret[1]

        import datetime
        now = str(datetime.datetime.now()).split(".")[0].replace(" ", "_")
        default = "Screenshot_%s_%s.png" % (self.vm.get_name(), now)

        path = self.err.browse_local(
            self.vm.conn, _("Save Virtual Machine Screenshot"),
            _type=("png", "PNG files"),
            dialog_type=Gtk.FileChooserAction.SAVE,
            browse_reason=self.config.CONFIG_DIR_SCREENSHOT,
            default_name=default)
        if not path:
            logging.debug("No screenshot path given, skipping save.")
            return

        filename = path
        if not filename.endswith(".png"):
            filename += ".png"
        file(filename, "wb").write(ret)


    ############################
    # Details/Hardware getters #
    ############################

    def get_config_boot_devs(self):
        boot_model = self.widget("config-boot-list").get_model()
        devs = []

        for row in boot_model:
            if row[BOOT_ACTIVE]:
                devs.append(row[BOOT_DEV_TYPE])

        return devs

    def get_config_cpu_model(self):
        cpu_list = self.widget("cpu-model")
        model = cpu_list.get_child().get_text()

        for row in cpu_list.get_model():
            if model == row[0]:
                return model, row[1].vendor

        return model, None

    def get_config_cpu_features(self):
        feature_list = self.widget("cpu-features")
        ret = []

        for row in feature_list.get_model():
            if row[1] in ["off", "model"]:
                continue
            ret.append(row)

        return ret

    ##############################
    # Details/Hardware listeners #
    ##############################

    def _browse_file(self, callback, is_media=False):
        if is_media:
            reason = self.config.CONFIG_DIR_ISO_MEDIA
        else:
            reason = self.config.CONFIG_DIR_IMAGE

        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.set_finish_cb(callback)
        self.storage_browser.set_browse_reason(reason)
        self.storage_browser.show(self.topwin, self.conn)

    def boot_kernel_toggled(self, src):
        self.widget("boot-kernel-box").set_sensitive(src.get_active())
        self.enable_apply(EDIT_KERNEL)

    def browse_kernel(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-kernel").set_text(path)
        self._browse_file(cb)
    def browse_initrd(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-initrd").set_text(path)
        self._browse_file(cb)
    def browse_dtb(self, src_ignore):
        def cb(ignore, path):
            self.widget("boot-dtb").set_text(path)
        self._browse_file(cb)

    def disable_apply(self):
        self.active_edits = []
        self.widget("config-apply").set_sensitive(False)
        self.widget("config-cancel").set_sensitive(False)

    def enable_apply(self, *arglist):
        edittype = arglist[-1]
        self.widget("config-apply").set_sensitive(True)
        self.widget("config-cancel").set_sensitive(True)
        if edittype not in self.active_edits:
            self.active_edits.append(edittype)

    # Memory
    def config_get_maxmem(self):
        return uiutil.spin_get_helper(self.widget("config-maxmem"))
    def config_get_memory(self):
        return uiutil.spin_get_helper(self.widget("config-memory"))

    def config_maxmem_changed(self, src_ignore):
        self.enable_apply(EDIT_MEM)

    def config_memory_changed(self, src_ignore):
        self.enable_apply(EDIT_MEM)

        maxadj = self.widget("config-maxmem")

        mem = self.config_get_memory()
        if maxadj.get_value() < mem:
            maxadj.set_value(mem)

        ignore, upper = maxadj.get_range()
        maxadj.set_range(mem, upper)

    def generate_cpuset(self):
        mem = int(self.vm.get_memory()) / 1024
        return virtinst.DomainNumatune.generate_cpuset(self.conn.get_backend(),
                                                       mem)

    # VCPUS
    def config_get_vcpus(self):
        return uiutil.spin_get_helper(self.widget("config-vcpus"))
    def config_get_maxvcpus(self):
        return uiutil.spin_get_helper(self.widget("config-maxvcpus"))

    def config_vcpupin_generate(self, ignore):
        try:
            pinstr = self.generate_cpuset()
        except Exception, e:
            return self.err.val_err(
                _("Error generating CPU configuration"), e)

        self.widget("config-vcpupin").set_text("")
        self.widget("config-vcpupin").set_text(pinstr)

    def config_vcpus_changed(self, ignore):
        self.enable_apply(EDIT_VCPUS)

        conn = self.vm.conn
        host_active_count = conn.host_active_processor_count()
        cur = self.config_get_vcpus()

        # Warn about overcommit
        warn = bool(cur > host_active_count)
        self.widget("config-vcpus-warn-box").set_visible(warn)

        maxadj = self.widget("config-maxvcpus")
        maxval = self.config_get_maxvcpus()
        if maxval < cur:
            maxadj.set_value(cur)
        ignore, upper = maxadj.get_range()
        maxadj.set_range(cur, upper)

    def config_maxvcpus_changed(self, ignore):
        self.enable_apply(EDIT_VCPUS)

    def config_cpu_copy_host(self, src_ignore):
        # Update UI with output copied from host
        try:
            CPU = virtinst.CPU(self.vm.conn.get_backend())
            CPU.copy_host_cpu()

            self._refresh_cpu_config(CPU)
            self._cpu_copy_host = True
        except Exception, e:
            self.err.show_err(_("Error copying host CPU: %s") % str(e))
            return

    def config_cpu_clear(self, src_ignore):
        try:
            CPU = virtinst.CPU(self.vm.conn.get_backend())
            CPU.clear()

            self._refresh_cpu_config(CPU)
        except Exception, e:
            self.err.show_err(_("Error clear CPU config: %s") % str(e))
            return

    def config_cpu_topology_enable(self, src):
        do_enable = src.get_active()
        self.widget("cpu-topology-table").set_sensitive(do_enable)
        self.enable_apply(EDIT_TOPOLOGY)

    # Boot device / Autostart
    def config_bootdev_selected(self, ignore):
        boot_row = self.get_boot_selection()
        boot_selection = boot_row and boot_row[BOOT_DEV_TYPE]
        boot_devs = self.get_config_boot_devs()
        up_widget = self.widget("config-boot-moveup")
        down_widget = self.widget("config-boot-movedown")

        down_widget.set_sensitive(bool(boot_devs and
                                       boot_selection and
                                       boot_selection in boot_devs and
                                       boot_selection != boot_devs[-1]))
        up_widget.set_sensitive(bool(boot_devs and boot_selection and
                                     boot_selection in boot_devs and
                                     boot_selection != boot_devs[0]))

    def config_boot_toggled(self, ignore, index):
        boot_model = self.widget("config-boot-list").get_model()
        boot_row = boot_model[index]
        is_active = boot_row[BOOT_ACTIVE]

        boot_row[BOOT_ACTIVE] = not is_active

        self.repopulate_boot_list(self.get_config_boot_devs(),
                                  boot_row[BOOT_DEV_TYPE])
        self.enable_apply(EDIT_BOOTORDER)

    def config_boot_move(self, src, move_up):
        ignore = src
        boot_row = self.get_boot_selection()
        if not boot_row:
            return

        boot_selection = boot_row[BOOT_DEV_TYPE]
        boot_devs = self.get_config_boot_devs()
        boot_idx = boot_devs.index(boot_selection)
        if move_up:
            new_idx = boot_idx - 1
        else:
            new_idx = boot_idx + 1

        if new_idx < 0 or new_idx >= len(boot_devs):
            # Somehow we got out of bounds
            return

        swap_dev = boot_devs[new_idx]
        boot_devs[new_idx] = boot_selection
        boot_devs[boot_idx] = swap_dev

        self.repopulate_boot_list(boot_devs, boot_selection)
        self.enable_apply(EDIT_BOOTORDER)

    # IO Tuning
    def iotune_changed(self, ignore):
        iotune_rbs = int(self.get_text("disk-iotune-rbs") or 0)
        iotune_ris = int(self.get_text("disk-iotune-ris") or 0)
        iotune_tbs = int(self.get_text("disk-iotune-tbs") or 0)
        iotune_tis = int(self.get_text("disk-iotune-tis") or 0)
        iotune_wbs = int(self.get_text("disk-iotune-wbs") or 0)
        iotune_wis = int(self.get_text("disk-iotune-wis") or 0)

        # libvirt doesn't support having read/write settings along side total
        # settings, so disable the widgets accordingly.

        have_rw_bytes = (iotune_rbs > 0 or
                         iotune_wbs > 0)
        have_t_bytes = (not have_rw_bytes and iotune_tbs > 0)

        self.widget("disk-iotune-rbs").set_sensitive(have_rw_bytes or not
                                                     have_t_bytes)
        self.widget("disk-iotune-wbs").set_sensitive(have_rw_bytes or not
                                                     have_t_bytes)
        self.widget("disk-iotune-tbs").set_sensitive(have_t_bytes or not
                                                     have_rw_bytes)

        if have_rw_bytes:
            self.widget("disk-iotune-tbs").set_value(0)
        elif have_t_bytes:
            self.widget("disk-iotune-rbs").set_value(0)
            self.widget("disk-iotune-wbs").set_value(0)

        have_rw_iops = (iotune_ris > 0 or iotune_wis > 0)
        have_t_iops = (not have_rw_iops and iotune_tis > 0)

        self.widget("disk-iotune-ris").set_sensitive(have_rw_iops or not
                                                     have_t_iops)
        self.widget("disk-iotune-wis").set_sensitive(have_rw_iops or not
                                                     have_t_iops)
        self.widget("disk-iotune-tis").set_sensitive(have_t_iops or not
                                                     have_rw_iops)

        if have_rw_iops:
            self.widget("disk-iotune-tis").set_value(0)
        elif have_t_iops:
            self.widget("disk-iotune-ris").set_value(0)
            self.widget("disk-iotune-wis").set_value(0)

        self.enable_apply(EDIT_DISK_IOTUNE)


    # CDROM Eject/Connect
    def toggle_storage_media(self, src_ignore):
        disk = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not disk:
            return

        curpath = disk.path
        devtype = disk.device

        try:
            if curpath:
                # Disconnect cdrom
                self.change_storage_media(disk, None)
                return
        except Exception, e:
            self.err.show_err((_("Error disconnecting media: %s") % e))
            return

        try:
            def change_cdrom_wrapper(src_ignore, disk, newpath):
                return self.change_storage_media(disk, newpath)

            # Launch 'Choose CD' dialog
            if self.media_choosers[devtype] is None:
                ret = vmmChooseCD(self.vm, disk)

                ret.connect("cdrom-chosen", change_cdrom_wrapper)
                self.media_choosers[devtype] = ret

            dialog = self.media_choosers[devtype]
            dialog.disk = disk

            dialog.show(self.topwin)
        except Exception, e:
            self.err.show_err((_("Error launching media dialog: %s") % e))
            return

    ##################################################
    # Details/Hardware config changes (apply button) #
    ##################################################

    def config_cancel(self, ignore=None):
        # Remove current changes and deactive 'apply' button
        self.hw_selected()

    def config_apply(self, ignore=None, row=None):
        pagetype = None
        devobj = None

        if not row:
            row = self.get_hw_row()
        if row:
            pagetype = row[HW_LIST_COL_TYPE]
            devobj = row[HW_LIST_COL_DEVICE]

        key = devobj
        ret = False

        try:
            if pagetype is HW_LIST_TYPE_GENERAL:
                ret = self.config_overview_apply()
            elif pagetype is HW_LIST_TYPE_CPU:
                ret = self.config_vcpus_apply()
            elif pagetype is HW_LIST_TYPE_MEMORY:
                ret = self.config_memory_apply()
            elif pagetype is HW_LIST_TYPE_BOOT:
                ret = self.config_boot_options_apply()
            elif pagetype is HW_LIST_TYPE_DISK:
                ret = self.config_disk_apply(key)
            elif pagetype is HW_LIST_TYPE_NIC:
                ret = self.config_network_apply(key)
            elif pagetype is HW_LIST_TYPE_GRAPHICS:
                ret = self.config_graphics_apply(key)
            elif pagetype is HW_LIST_TYPE_SOUND:
                ret = self.config_sound_apply(key)
            elif pagetype is HW_LIST_TYPE_VIDEO:
                ret = self.config_video_apply(key)
            elif pagetype is HW_LIST_TYPE_WATCHDOG:
                ret = self.config_watchdog_apply(key)
            elif pagetype is HW_LIST_TYPE_SMARTCARD:
                ret = self.config_smartcard_apply(key)
            elif pagetype is HW_LIST_TYPE_CONTROLLER:
                ret = self.config_controller_apply(key)
            elif pagetype is HW_LIST_TYPE_FILESYSTEM:
                ret = self.config_filesystem_apply(key)
            else:
                ret = False
        except Exception, e:
            return self.err.show_err(_("Error apply changes: %s") % e)

        if ret is not False:
            self.disable_apply()
        return True

    def get_text(self, widgetname, strip=True, checksens=False):
        widget = self.widget(widgetname)
        if (checksens and
            (not widget.is_sensitive() or not widget.is_visible())):
            return ""

        ret = widget.get_text()
        if strip:
            ret = ret.strip()
        return ret

    def edited(self, pagetype):
        return pagetype in self.active_edits

    def make_apply_data(self):
        definefuncs = []
        defineargs = []
        hotplugfuncs = []
        hotplugargs = []

        def add_define(func, *args):
            definefuncs.append(func)
            defineargs.append(args)
        def add_hotplug(func, *args):
            hotplugfuncs.append(func)
            hotplugargs.append(args)

        return (definefuncs, defineargs, add_define,
                hotplugfuncs, hotplugargs, add_hotplug)

    # Overview section
    def config_overview_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_NAME):
            name = self.widget("overview-name").get_text()
            add_define(self.vm.define_name, name)

        if self.edited(EDIT_TITLE):
            title = self.widget("overview-title").get_text()
            add_define(self.vm.define_title, title)
            add_hotplug(self.vm.hotplug_title, title)

        if self.edited(EDIT_MACHTYPE):
            machtype = self.get_combo_entry("machine-type")
            add_define(self.vm.define_machtype, machtype)

        if self.edited(EDIT_DESC):
            desc_widget = self.widget("overview-description")
            desc = desc_widget.get_buffer().get_property("text") or ""
            add_define(self.vm.define_description, desc)
            add_hotplug(self.vm.hotplug_description, desc)

        return self._change_config_helper(df, da, hf, ha)

    # CPUs
    def config_vcpus_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()

        if self.edited(EDIT_VCPUS):
            vcpus = self.config_get_vcpus()
            maxv = self.config_get_maxvcpus()
            add_define(self.vm.define_vcpus, vcpus, maxv)
            add_hotplug(self.vm.hotplug_vcpus, vcpus)

        if self.edited(EDIT_CPUSET):
            cpuset = self.get_text("config-vcpupin")
            add_define(self.vm.define_cpuset, cpuset)

        if self.edited(EDIT_CPU):
            model, vendor = self.get_config_cpu_model()
            features = self.get_config_cpu_features()
            add_define(self.vm.define_cpu,
                       model, vendor, self._cpu_copy_host, features)

        if self.edited(EDIT_TOPOLOGY):
            do_top = self.widget("cpu-topology-enable").get_active()
            sockets = self.widget("cpu-sockets").get_value()
            cores = self.widget("cpu-cores").get_value()
            threads = self.widget("cpu-threads").get_value()
            if not do_top:
                sockets = None
                cores = None
                threads = None

            add_define(self.vm.define_cpu_topology, sockets, cores, threads)

        ret = self._change_config_helper(df, da, hf, ha)
        if ret:
            self._cpu_copy_host = False
        return ret

    # Memory
    def config_memory_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()

        if self.edited(EDIT_MEM):
            curmem = None
            maxmem = self.config_get_maxmem()
            if self.widget("config-memory").get_sensitive():
                curmem = self.config_get_memory()

            if curmem:
                curmem = int(curmem) * 1024
            if maxmem:
                maxmem = int(maxmem) * 1024

            add_define(self.vm.define_both_mem, curmem, maxmem)
            add_hotplug(self.vm.hotplug_both_mem, curmem, maxmem)

        return self._change_config_helper(df, da, hf, ha)

    # Boot device / Autostart
    def config_boot_options_apply(self):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_AUTOSTART):
            auto = self.widget("config-autostart")
            try:
                self.vm.set_autostart(auto.get_active())
            except Exception, e:
                self.err.show_err(
                    (_("Error changing autostart value: %s") % str(e)))
                return False

        if self.edited(EDIT_BOOTORDER):
            bootdevs = self.get_config_boot_devs()
            add_define(self.vm.set_boot_device, bootdevs)

        if self.edited(EDIT_BOOTMENU):
            bootmenu = self.widget("boot-menu").get_active()
            add_define(self.vm.set_boot_menu, bootmenu)

        if self.edited(EDIT_KERNEL):
            kernel = self.get_text("boot-kernel", checksens=True)
            initrd = self.get_text("boot-initrd", checksens=True)
            dtb = self.get_text("boot-dtb", checksens=True)
            args = self.get_text("boot-kernel-args", checksens=True)

            if initrd and not kernel:
                return self.err.val_err(
                    _("Cannot set initrd without specifying a kernel path"))
            if args and not kernel:
                return self.err.val_err(
                    _("Cannot set kernel arguments without specifying a kernel path"))

            add_define(self.vm.set_boot_kernel, kernel, initrd, dtb, args)

        if self.edited(EDIT_INIT):
            init = self.get_text("boot-init-path")
            if not init:
                return self.err.val_err(_("An init path must be specified"))
            add_define(self.vm.set_boot_init, init)

        return self._change_config_helper(df, da, hf, ha)

    # CDROM
    def change_storage_media(self, dev_id_info, newpath):
        return self._change_config_helper(self.vm.define_storage_media,
                                          (dev_id_info, newpath),
                                          self.vm.hotplug_storage_media,
                                          (dev_id_info, newpath))

    # Disk options
    def config_disk_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_DISK_RO):
            do_readonly = self.widget("disk-readonly").get_active()
            add_define(self.vm.define_disk_readonly, dev_id_info, do_readonly)

        if self.edited(EDIT_DISK_SHARE):
            do_shareable = self.widget("disk-shareable").get_active()
            add_define(self.vm.define_disk_shareable,
                       dev_id_info, do_shareable)

        if self.edited(EDIT_DISK_REMOVABLE):
            do_removable = bool(self.widget("disk-removable").get_active())
            add_define(self.vm.define_disk_removable, dev_id_info, do_removable)

        if self.edited(EDIT_DISK_CACHE):
            cache = self.get_combo_entry("disk-cache")
            add_define(self.vm.define_disk_cache, dev_id_info, cache)

        if self.edited(EDIT_DISK_IO):
            io = self.get_combo_entry("disk-io")
            add_define(self.vm.define_disk_io, dev_id_info, io)

        if self.edited(EDIT_DISK_FORMAT):
            fmt = self.get_combo_entry("disk-format")
            add_define(self.vm.define_disk_driver_type, dev_id_info, fmt)

        if self.edited(EDIT_DISK_SERIAL):
            serial = self.get_text("disk-serial")
            add_define(self.vm.define_disk_serial, dev_id_info, serial)

        if self.edited(EDIT_DISK_IOTUNE):
            iotune_rbs = int(self.widget("disk-iotune-rbs").get_value() * 1024)
            iotune_ris = int(self.widget("disk-iotune-ris").get_value())
            iotune_tbs = int(self.widget("disk-iotune-tbs").get_value() * 1024)
            iotune_tis = int(self.widget("disk-iotune-tis").get_value())
            iotune_wbs = int(self.widget("disk-iotune-wbs").get_value() * 1024)
            iotune_wis = int(self.widget("disk-iotune-wis").get_value())

            add_define(self.vm.define_disk_iotune_rbs, dev_id_info, iotune_rbs)
            add_define(self.vm.define_disk_iotune_ris, dev_id_info, iotune_ris)
            add_define(self.vm.define_disk_iotune_tbs, dev_id_info, iotune_tbs)
            add_define(self.vm.define_disk_iotune_tis, dev_id_info, iotune_tis)
            add_define(self.vm.define_disk_iotune_wbs, dev_id_info, iotune_wbs)
            add_define(self.vm.define_disk_iotune_wis, dev_id_info, iotune_wis)

        # Do this last since it can change uniqueness info of the dev
        if self.edited(EDIT_DISK_BUS):
            bus = self.get_combo_entry("disk-bus")
            addr = None
            if bus == "spapr-vscsi":
                bus = "scsi"
                addr = "spapr-vio"
            add_define(self.vm.define_disk_bus, dev_id_info, bus, addr)

        return self._change_config_helper(df, da, hf, ha)

    # Audio options
    def config_sound_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_SOUND_MODEL):
            model = self.get_combo_entry("sound-model")
            if model:
                add_define(self.vm.define_sound_model, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Smartcard options
    def config_smartcard_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_SMARTCARD_MODE):
            model = self.get_combo_entry("smartcard-mode")
            if model:
                add_define(self.vm.define_smartcard_mode, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Network options
    def config_network_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_NET_MODEL):
            model = self.get_combo_entry("network-model")
            addr = None
            if model == "spapr-vlan":
                addr = "spapr-vio"
            add_define(self.vm.define_network_model, dev_id_info, model, addr)

        if self.edited(EDIT_NET_SOURCE):
            mode = None
            net_list = self.widget("network-source")
            net_bridge = self.widget("network-bridge")
            nettype, source = sharedui.get_network_selection(net_list,
                                                             net_bridge)
            if nettype == "direct":
                mode = self.get_combo_entry("network-source-mode")

            add_define(self.vm.define_network_source, dev_id_info,
                       nettype, source, mode)

        if self.edited(EDIT_NET_VPORT):
            vport_type = self.get_text("vport-type")
            vport_managerid = self.get_text("vport-managerid")
            vport_typeid = self.get_text("vport-typeid")
            vport_idver = self.get_text("vport-typeidversion")
            vport_instid = self.get_text("vport-instanceid")

            add_define(self.vm.define_virtualport, dev_id_info,
                       vport_type, vport_managerid, vport_typeid,
                       vport_idver, vport_instid)

        return self._change_config_helper(df, da, hf, ha)

    # Graphics options
    def config_graphics_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()

        if self.edited(EDIT_GFX_PASSWD) or self.edited(EDIT_GFX_USE_PASSWD):
            use_passwd = self.widget("gfx-use-password").get_active()
            if use_passwd:
                passwd = self.get_text("gfx-password", strip=False) or ""
            else:
                passwd = None
            add_define(self.vm.define_graphics_password, dev_id_info, passwd)
            add_hotplug(self.vm.hotplug_graphics_password, dev_id_info,
                        passwd)

        if self.edited(EDIT_GFX_KEYMAP):
            keymap = self.get_combo_entry("gfx-keymap")
            add_define(self.vm.define_graphics_keymap, dev_id_info, keymap)

        # Do this last since it can change graphics unique ID
        if self.edited(EDIT_GFX_TYPE):
            gtype = self.get_combo_entry("gfx-type")
            add_define(self.vm.define_graphics_type, dev_id_info, gtype)

        return self._change_config_helper(df, da, hf, ha)

    # Video options
    def config_video_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_VIDEO_MODEL):
            model = self.get_combo_entry("video-model")
            if model:
                add_define(self.vm.define_video_model, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Controller options
    def config_controller_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_CONTROLLER_MODEL):
            model = self.get_combo_entry("controller-model")
            if model:
                add_define(self.vm.define_controller_model, dev_id_info, model)

        return self._change_config_helper(df, da, hf, ha)

    # Watchdog options
    def config_watchdog_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_WATCHDOG_MODEL):
            model = self.get_combo_entry("watchdog-model")
            add_define(self.vm.define_watchdog_model, dev_id_info, model)

        if self.edited(EDIT_WATCHDOG_ACTION):
            action = self.get_combo_entry("watchdog-action")
            add_define(self.vm.define_watchdog_action, dev_id_info, action)

        return self._change_config_helper(df, da, hf, ha)

    # Filesystem options
    def config_filesystem_apply(self, dev_id_info):
        df, da, add_define, hf, ha, add_hotplug = self.make_apply_data()
        ignore = add_hotplug

        if self.edited(EDIT_FS):
            self.fsDetails.validate_page_filesystem()
            add_define(self.vm.define_filesystem, dev_id_info,
                       self.fsDetails.get_dev())

        return self._change_config_helper(df, da, hf, ha)

    # Device removal
    def remove_device(self, dev_type, dev_id_info):
        logging.debug("Removing device: %s %s", dev_type, dev_id_info)

        if not self.err.chkbox_helper(self.config.get_confirm_removedev,
            self.config.set_confirm_removedev,
            text1=(_("Are you sure you want to remove this device?"))):
            return

        # Define the change
        try:
            self.vm.remove_device(dev_id_info)
        except Exception, e:
            self.err.show_err(_("Error Removing Device: %s" % str(e)))
            return

        # Try to hot remove
        detach_err = False
        try:
            if self.vm.is_active():
                self.vm.detach_device(dev_id_info)
        except Exception, e:
            logging.debug("Device could not be hotUNplugged: %s", str(e))
            detach_err = (str(e), "".join(traceback.format_exc()))

        if not detach_err:
            self.disable_apply()
            return

        self.err.show_err(
            _("Device could not be removed from the running machine"),
            details=(detach_err[0] + "\n\n" + detach_err[1]),
            text2=_("This change will take effect after the next guest "
                    "shutdown."),
            buttons=Gtk.ButtonsType.OK,
            dialog_type=Gtk.MessageType.INFO)

    # Generic config change helpers
    def _change_config_helper(self,
                              define_funcs, define_funcs_args,
                              hotplug_funcs=None, hotplug_funcs_args=None):
        """
        Requires at least a 'define' function and arglist to be specified
        (a function where we change the inactive guest config).

        Arguments can be a single arg or a list or appropriate arg type (e.g.
        a list of functions for define_funcs)
        """
        define_funcs = util.listify(define_funcs)
        define_funcs_args = util.listify(define_funcs_args)
        hotplug_funcs = util.listify(hotplug_funcs)
        hotplug_funcs_args = util.listify(hotplug_funcs_args)

        hotplug_err = []
        active = self.vm.is_active()

        # Hotplug change
        func = None
        if active and hotplug_funcs:
            for idx in range(len(hotplug_funcs)):
                func = hotplug_funcs[idx]
                args = hotplug_funcs_args[idx]
                try:
                    func(*args)
                except Exception, e:
                    logging.debug("Hotplug failed: func=%s: %s",
                                  func, str(e))
                    hotplug_err.append((str(e),
                                        "".join(traceback.format_exc())))

        # Persistent config change
        try:
            for idx in range(len(define_funcs)):
                func = define_funcs[idx]
                args = define_funcs_args[idx]
                func(*args)
            if define_funcs:
                self.vm.redefine_cached()
        except Exception, e:
            self.err.show_err((_("Error changing VM configuration: %s") %
                              str(e)))
            # If we fail, make sure we flush the cache
            self.vm.refresh_xml()
            return False


        if (hotplug_err or
            (active and not len(hotplug_funcs) == len(define_funcs))):
            if len(define_funcs) > 1:
                msg = _("Some changes may require a guest shutdown "
                        "to take effect.")
            else:
                msg = _("These changes will take effect after "
                        "the next guest shutdown.")

            dtype = hotplug_err and Gtk.MessageType.WARNING or Gtk.MessageType.INFO
            hotplug_msg = ""
            for err1, tb in hotplug_err:
                hotplug_msg += (err1 + "\n\n" + tb + "\n")

            self.err.show_err(msg,
                              details=hotplug_msg,
                              buttons=Gtk.ButtonsType.OK,
                              dialog_type=dtype)

        return True

    ########################
    # Details page refresh #
    ########################

    def refresh_resources(self, ignore):
        details = self.widget("details-pages")
        page = details.get_current_page()

        # If the dialog is visible, we want to make sure the XML is always
        # up to date
        try:
            if self.is_visible():
                self.vm.refresh_xml()
        except libvirt.libvirtError, e:
            if util.exception_is_libvirt_error(e, "VIR_ERR_NO_DOMAIN"):
                self.close()
                return
            raise

        # Stats page needs to be refreshed every tick
        if (page == DETAILS_PAGE_DETAILS and
            self.get_hw_selection(HW_LIST_COL_TYPE) == HW_LIST_TYPE_STATS):
            self.refresh_stats_page()

    def page_refresh(self, page):
        if page != DETAILS_PAGE_DETAILS:
            return

        # This function should only be called when the VM xml actually
        # changes (not everytime it is refreshed). This saves us from blindly
        # parsing the xml every tick

        # Add / remove new devices
        self.repopulate_hw_list()

        pagetype = self.get_hw_selection(HW_LIST_COL_TYPE)
        if pagetype is None:
            return

        if self.widget("config-apply").get_sensitive():
            # Apply button sensitive means user is making changes, don't
            # erase them
            return

        self.hw_selected(page=pagetype)

    def refresh_overview_page(self):
        # Basic details
        self.widget("overview-name").set_text(self.vm.get_name())
        self.widget("overview-uuid").set_text(self.vm.get_uuid())
        desc = self.vm.get_description() or ""
        desc_widget = self.widget("overview-description")
        desc_widget.get_buffer().set_text(desc)

        title = self.vm.get_title()
        self.widget("overview-title").set_sensitive(self.vm.title_supported)
        self.widget("overview-title").set_text(title or "")

        # Hypervisor Details
        self.widget("overview-hv").set_text(self.vm.get_pretty_hv_type())
        arch = self.vm.get_arch() or _("Unknown")
        emu = self.vm.get_emulator() or _("None")
        self.widget("overview-arch").set_text(arch)
        self.widget("overview-emulator").set_text(emu)

        # Machine settings
        machtype = self.vm.get_machtype()
        if not arch in ["i686", "x86_64"]:
            if machtype is not None:
                self.set_combo_entry("machine-type", machtype)

    def refresh_inspection_page(self):
        inspection_supported = self.config.support_inspection
        uiutil.set_grid_row_visible(self.widget("details-overview-error"),
                                       self.vm.inspection.error)
        if self.vm.inspection.error:
            msg = _("Error while inspecting the guest configuration")
            self.widget("details-overview-error").set_text(msg)

        # Operating System (ie. inspection data)
        self.widget("details-inspection-os").set_visible(inspection_supported)
        if inspection_supported:
            hostname = self.vm.inspection.hostname
            if not hostname:
                hostname = _("unknown")
            self.widget("inspection-hostname").set_text(hostname)
            product_name = self.vm.inspection.product_name
            if not product_name:
                product_name = _("unknown")
            self.widget("inspection-product-name").set_text(product_name)

        # Applications (also inspection data)
        self.widget("details-inspection-apps").set_visible(inspection_supported)
        if inspection_supported:
            apps = self.vm.inspection.applications or []
            apps_list = self.widget("inspection-apps")
            apps_model = apps_list.get_model()
            apps_model.clear()
            for app in apps:
                name = ""
                if app["app_name"]:
                    name = app["app_name"]
                if app["app_display_name"]:
                    name = app["app_display_name"]
                version = ""
                if app["app_version"]:
                    version = app["app_version"]
                if app["app_release"]:
                    version += "-" + app["app_release"]
                summary = ""
                if app["app_summary"]:
                    summary = app["app_summary"]

                apps_model.append([name, version, summary])

    def refresh_stats_page(self):
        def _dsk_rx_tx_text(rx, tx, unit):
            return ('<span color="#82003B">%(rx)d %(unit)s read</span> '
                    '<span color="#295C45">%(tx)d %(unit)s write</span>' %
                    {"rx": rx, "tx": tx, "unit": unit})
        def _net_rx_tx_text(rx, tx, unit):
            return ('<span color="#82003B">%(rx)d %(unit)s in</span> '
                    '<span color="#295C45">%(tx)d %(unit)s out</span>' %
                    {"rx": rx, "tx": tx, "unit": unit})

        cpu_txt = _("Disabled")
        mem_txt = _("Disabled")
        dsk_txt = _("Disabled")
        net_txt = _("Disabled")

        cpu_txt = "%d %%" % self.vm.guest_cpu_time_percentage()

        cur_vm_memory = self.vm.stats_memory()
        vm_memory = self.vm.maximum_memory()
        mem_txt = "%s of %s" % (util.pretty_mem(cur_vm_memory),
                                util.pretty_mem(vm_memory))

        if self.config.get_stats_enable_disk_poll():
            dsk_txt = _dsk_rx_tx_text(self.vm.disk_read_rate(),
                                      self.vm.disk_write_rate(), "KB/s")

        if self.config.get_stats_enable_net_poll():
            net_txt = _net_rx_tx_text(self.vm.network_rx_rate(),
                                      self.vm.network_tx_rate(), "KB/s")

        self.widget("overview-cpu-usage-text").set_text(cpu_txt)
        self.widget("overview-memory-usage-text").set_text(mem_txt)
        self.widget("overview-network-traffic-text").set_markup(net_txt)
        self.widget("overview-disk-usage-text").set_markup(dsk_txt)

        self.cpu_usage_graph.set_property("data_array",
                                          self.vm.guest_cpu_time_vector())
        self.memory_usage_graph.set_property("data_array",
                                             self.vm.stats_memory_vector())
        self.disk_io_graph.set_property("data_array",
                                        self.vm.disk_io_vector())
        self.network_traffic_graph.set_property("data_array",
                                                self.vm.network_traffic_vector())

    def _refresh_cpu_count(self):
        conn = self.vm.conn
        host_active_count = conn.host_active_processor_count()
        maxvcpus = self.vm.vcpu_max_count()
        curvcpus = self.vm.vcpu_count()

        curadj = self.widget("config-vcpus")
        maxadj = self.widget("config-maxvcpus")
        curadj.set_value(int(curvcpus))
        maxadj.set_value(int(maxvcpus))

        self.widget("state-host-cpus").set_text(str(host_active_count))

        # Warn about overcommit
        warn = bool(self.config_get_vcpus() > host_active_count)
        self.widget("config-vcpus-warn-box").set_visible(warn)

    def _refresh_cpu_config(self, cpu):
        feature_ui = self.widget("cpu-features")
        model = cpu.model or ""
        caps = self.vm.conn.caps

        capscpu = None
        try:
            arch = self.vm.get_arch()
            if arch:
                cpu_values = caps.get_cpu_values(arch)
                for c in cpu_values.cpus:
                    if model and c.model == model:
                        capscpu = c
                        break
        except:
            pass

        show_top = bool(cpu.sockets or cpu.cores or cpu.threads)
        sockets = cpu.sockets or 1
        cores = cpu.cores or 1
        threads = cpu.threads or 1

        self.widget("cpu-topology-enable").set_active(show_top)
        self.widget("cpu-model").get_child().set_text(model)
        self.widget("cpu-sockets").set_value(sockets)
        self.widget("cpu-cores").set_value(cores)
        self.widget("cpu-threads").set_value(threads)

        def get_feature_policy(name):
            for f in cpu.features:
                if f.name == name:
                    return f.policy

            if capscpu:
                for f in capscpu.features:
                    if f == name:
                        return "model"
            return "off"

        for row in feature_ui.get_model():
            row[1] = get_feature_policy(row[0])

    def refresh_config_cpu(self):
        self._cpu_copy_host = False
        cpu = self.vm.get_cpu_config()

        self._refresh_cpu_count()
        self._refresh_cpu_config(cpu)

    def refresh_config_memory(self):
        host_mem_widget = self.widget("state-host-memory")
        host_mem = self.vm.conn.host_memory_size() / 1024
        vm_cur_mem = self.vm.get_memory() / 1024.0
        vm_max_mem = self.vm.maximum_memory() / 1024.0

        host_mem_widget.set_text("%d MB" % (int(round(host_mem))))

        curmem = self.widget("config-memory")
        maxmem = self.widget("config-maxmem")
        curmem.set_value(int(round(vm_cur_mem)))
        maxmem.set_value(int(round(vm_max_mem)))

        if not self.widget("config-memory").get_sensitive():
            ignore, upper = maxmem.get_range()
            maxmem.set_range(curmem.get_value(), upper)


    def refresh_disk_page(self):
        disk = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not disk:
            return

        path = disk.path
        devtype = disk.device
        ro = disk.read_only
        share = disk.shareable
        bus = disk.bus
        removable = disk.removable
        addr = disk.address.type
        idx = disk.disk_bus_index
        cache = disk.driver_cache
        io = disk.driver_io
        driver_type = disk.driver_type or ""
        serial = disk.serial

        iotune_rbs = (disk.iotune_rbs or 0) / 1024
        iotune_ris = (disk.iotune_ris or 0)
        iotune_tbs = (disk.iotune_tbs or 0) / 1024
        iotune_tis = (disk.iotune_tis or 0)
        iotune_wbs = (disk.iotune_wbs or 0) / 1024
        iotune_wis = (disk.iotune_wis or 0)

        show_format = (not self.is_customize_dialog or
                       disk.path_exists(disk.conn, disk.path))

        size = _("Unknown")
        if not path:
            size = "-"
        else:
            vol = self.conn.get_vol_by_path(path)
            if vol:
                size = vol.get_pretty_capacity()
            elif not self.conn.is_remote():
                ignore, val = virtinst.VirtualDisk.stat_local_path(path)
                if val != 0:
                    size = prettyify_bytes(val)

        is_cdrom = (devtype == virtinst.VirtualDisk.DEVICE_CDROM)
        is_floppy = (devtype == virtinst.VirtualDisk.DEVICE_FLOPPY)
        is_usb = (bus == "usb")

        can_set_removable = (is_usb and (self.conn.is_qemu() or
                                         self.conn.is_test_conn()))
        if removable is None:
            removable = False
        else:
            can_set_removable = True

        if addr == "spapr-vio":
            bus = "spapr-vscsi"

        pretty_name = prettyify_disk(devtype, bus, idx)

        self.widget("disk-source-path").set_text(path or "-")
        self.widget("disk-target-type").set_text(pretty_name)

        self.widget("disk-readonly").set_active(ro)
        self.widget("disk-readonly").set_sensitive(not is_cdrom)
        self.widget("disk-shareable").set_active(share)
        self.widget("disk-removable").set_active(removable)
        uiutil.set_grid_row_visible(self.widget("disk-removable"),
                                       can_set_removable)
        self.widget("disk-size").set_text(size)
        self.set_combo_entry("disk-cache", cache)
        self.set_combo_entry("disk-io", io)

        self.widget("disk-format").set_sensitive(show_format)
        self.widget("disk-format").get_child().set_text(driver_type)

        no_default = not self.is_customize_dialog

        self.populate_disk_bus_combo(devtype, no_default)
        self.set_combo_entry("disk-bus", bus)
        self.widget("disk-serial").set_text(serial or "")

        self.widget("disk-iotune-rbs").set_value(iotune_rbs)
        self.widget("disk-iotune-ris").set_value(iotune_ris)
        self.widget("disk-iotune-tbs").set_value(iotune_tbs)
        self.widget("disk-iotune-tis").set_value(iotune_tis)
        self.widget("disk-iotune-wbs").set_value(iotune_wbs)
        self.widget("disk-iotune-wis").set_value(iotune_wis)

        button = self.widget("config-cdrom-connect")
        if is_cdrom or is_floppy:
            if not path:
                # source device not connected
                button.set_label(Gtk.STOCK_CONNECT)
            else:
                button.set_label(Gtk.STOCK_DISCONNECT)
            button.show()
        else:
            button.hide()

    def refresh_network_page(self):
        net = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not net:
            return

        nettype = net.type
        source = net.source
        source_mode = net.source_mode
        model = net.model

        netobj = None
        if nettype == virtinst.VirtualNetworkInterface.TYPE_VIRTUAL:
            name_dict = {}
            for uuid in self.conn.list_net_uuids():
                vnet = self.conn.get_net(uuid)
                name = vnet.get_name()
                name_dict[name] = vnet

            if source and source in name_dict:
                netobj = name_dict[source]

        desc = sharedui.pretty_network_desc(nettype, source, netobj)

        self.widget("network-mac-address").set_text(net.macaddr)
        sharedui.populate_network_list(
                    self.widget("network-source"),
                    self.conn)
        self.widget("network-source").set_active(-1)

        self.widget("network-bridge").set_text("")
        def compare_network(model, info):
            for idx in range(len(model)):
                row = model[idx]
                if row[0] == info[0] and row[1] == info[1]:
                    return True, idx

            if info[0] == virtinst.VirtualNetworkInterface.TYPE_BRIDGE:
                idx = (len(model) - 1)
                self.widget("network-bridge").set_text(str(info[1]))
                return True, idx

            return False, 0

        self.set_combo_entry("network-source",
                             (nettype, source), label=desc,
                             comparefunc=compare_network)

        is_direct = (nettype == "direct")
        uiutil.set_grid_row_visible(self.widget("network-source-mode"),
                                       is_direct)
        self.widget("vport-expander").set_visible(is_direct)

        # source mode
        vmmAddHardware.populate_network_source_mode_combo(self.vm,
                            self.widget("network-source-mode"))
        self.set_combo_entry("network-source-mode", source_mode)

        # Virtualport config
        vport = net.virtualport
        self.widget("vport-type").set_text(vport.type or "")
        self.widget("vport-managerid").set_text(str(vport.managerid) or "")
        self.widget("vport-typeid").set_text(str(vport.typeid) or "")
        self.widget("vport-typeidversion").set_text(
                                str(vport.typeidversion) or "")
        self.widget("vport-instanceid").set_text(vport.instanceid or "")

        vmmAddHardware.populate_network_model_combo(self.vm,
                                          self.widget("network-model"))
        self.set_combo_entry("network-model", model)

    def refresh_input_page(self):
        inp = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not inp:
            return

        ident = "%s:%s" % (inp.type, inp.bus)
        if ident == "tablet:usb":
            dev = _("EvTouch USB Graphics Tablet")
        elif ident == "mouse:usb":
            dev = _("Generic USB Mouse")
        elif ident == "mouse:xen":
            dev = _("Xen Mouse")
        elif ident == "mouse:ps2":
            dev = _("PS/2 Mouse")
        else:
            dev = inp.bus + " " + inp.type

        if inp.type == "tablet":
            mode = _("Absolute Movement")
        else:
            mode = _("Relative Movement")

        self.widget("input-dev-type").set_text(dev)
        self.widget("input-dev-mode").set_text(mode)

        # Can't remove primary Xen or PS/2 mice
        if inp.type == "mouse" and inp.bus in ("xen", "ps2"):
            self.widget("config-remove").set_sensitive(False)
        else:
            self.widget("config-remove").set_sensitive(True)

    def refresh_graphics_page(self):
        gfx = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not gfx:
            return

        table = self.widget("graphics-table")
        table.foreach(lambda w, ignore: w.hide(), ())

        def show_row(name):
            uiutil.set_grid_row_visible(self.widget(name), True)

        def port_to_string(port):
            if port is None:
                return "-"
            return (port == -1 and _("Automatically allocated") or str(port))

        gtype = gfx.type
        is_vnc = (gtype == "vnc")
        is_sdl = (gtype == "sdl")
        is_spice = (gtype == "spice")
        is_other = not (True in [is_vnc, is_sdl, is_spice])

        title = (_("%(graphicstype)s Server") %
                  {"graphicstype" : gfx.pretty_type_simple(gtype)})

        settype = ""
        if is_vnc or is_spice:
            use_passwd = gfx.passwd is not None

            show_row("gfx-password-box")
            show_row("gfx-address")
            show_row("gfx-port")
            show_row("gfx-keymap")

            self.widget("gfx-port").set_text(port_to_string(gfx.port))
            self.widget("gfx-address").set_text(gfx.listen or "127.0.0.1")
            self.set_combo_entry("gfx-keymap", gfx.keymap or None)

            self.widget("gfx-password").set_text(gfx.passwd or "")
            self.widget("gfx-use-password").set_active(use_passwd)
            self.widget("gfx-password").set_sensitive(use_passwd)

            settype = gtype

        if is_spice:
            show_row("gfx-tlsport")
            self.widget("gfx-tlsport").set_text(port_to_string(gfx.tlsPort))

        if is_sdl:
            title = _("Local SDL Window")

            show_row("gfx-display")
            show_row("gfx-xauth")
            self.widget("gfx-display").set_text(gfx.display or _("Unknown"))
            self.widget("gfx-xauth").set_text(gfx.xauth or _("Unknown"))

        if is_other:
            settype = gfx.pretty_type_simple(gtype)

        if settype:
            show_row("gfx-type")
            self.set_combo_entry("gfx-type", gtype, label=settype)

        self.widget("graphics-title").set_markup("<b>%s</b>" % title)


    def refresh_sound_page(self):
        sound = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not sound:
            return

        self.set_combo_entry("sound-model", sound.model)

    def refresh_smartcard_page(self):
        sc = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not sc:
            return

        self.set_combo_entry("smartcard-mode", sc.mode)

    def refresh_redir_page(self):
        rd = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not rd:
            return

        address = build_redir_label(rd)[0] or "-"

        devlabel = "<b>Redirected %s Device</b>" % rd.bus.upper()
        self.widget("redir-title").set_markup(devlabel)
        self.widget("redir-address").set_text(address)

        self.widget("redir-type").set_text(rd.type)

    def refresh_tpm_page(self):
        tpmdev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not tpmdev:
            return

        def show_ui(param, val=None):
            widgetname = "tpm-" + param.replace("_", "-")
            doshow = tpmdev.supports_property(param)

            if not val and doshow:
                val = getattr(tpmdev, param)

            uiutil.set_grid_row_visible(self.widget(widgetname), doshow)
            self.widget(widgetname).set_text(val or "-")

        dev_type = tpmdev.type
        self.widget("tpm-dev-type").set_text(
                virtinst.VirtualTPMDevice.get_pretty_type(dev_type))

        # Device type specific properties, only show if apply to the cur dev
        show_ui("device_path")

    def refresh_panic_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        def show_ui(param, val=None):
            widgetname = "panic-" + param.replace("_", "-")
            if not val:
                val = getattr(dev, param)
                if not val:
                    propername = param.upper() + "_DEFAULT"
                    val = getattr(virtinst.VirtualPanicDevice, propername, "-").upper()

            uiutil.set_grid_row_visible(self.widget(widgetname), True)
            self.widget(widgetname).set_text(val or "-")

        ptyp = virtinst.VirtualPanicDevice.get_pretty_type(dev.type)
        show_ui("type", ptyp)
        show_ui("iobase")

    def refresh_rng_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        values = {
            "rng-bind-host" : "bind_host",
            "rng-bind-service" : "bind_service",
            "rng-connect-host" : "connect_host",
            "rng-connect-service" : "connect_service",
            "rng-type" : "type",
            "rng-device" : "device",
            "rng-backend-type" : "backend_type",
            "rng-rate-bytes" : "rate_bytes",
            "rng-rate-period" : "rate_period"
        }
        rewriter = {
            "rng-type" : lambda x:
            VirtualRNGDevice.get_pretty_type(x),
            "rng-backend-type" : lambda x:
            VirtualRNGDevice.get_pretty_backend_type(x),
        }

        def set_visible(widget, v):
            uiutil.set_grid_row_visible(self.widget(widget), v)

        is_egd = dev.type == VirtualRNGDevice.TYPE_EGD
        udp = dev.backend_type == VirtualRNGDevice.BACKEND_TYPE_UDP
        bind = VirtualRNGDevice.BACKEND_MODE_BIND in dev.backend_mode()

        set_visible("rng-device", not is_egd)
        set_visible("rng-mode", is_egd and not udp)
        set_visible("rng-backend-type", is_egd)
        set_visible("rng-connect-host", is_egd and (udp or not bind))
        set_visible("rng-connect-service", is_egd and (udp or not bind))
        set_visible("rng-bind-host", is_egd and (udp or bind))
        set_visible("rng-bind-service", is_egd and (udp or bind))

        for k, prop in values.items():
            val = "-"
            if dev.supports_property(prop):
                val = getattr(dev, prop) or "-"
                r = rewriter.get(k)
                if r:
                    val = r(val)
            self.widget(k).set_text(val)

        if is_egd and not udp:
            mode = VirtualRNGDevice.get_pretty_mode(dev.backend_mode()[0])
            self.widget("rng-mode").set_text(mode)

    def refresh_char_page(self):
        chardev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not chardev:
            return

        show_target_type = not (chardev.virtual_device_type in
                                ["serial", "parallel"])
        show_target_name = chardev.virtual_device_type == "channel"

        def show_ui(param, val=None):
            widgetname = "char-" + param.replace("_", "-")
            doshow = chardev.supports_property(param, ro=True)

            # Exception: don't show target type for serial/parallel
            if (param == "target_type" and not show_target_type):
                doshow = False
            if (param == "target_name" and not show_target_name):
                doshow = False

            if not val and doshow:
                val = getattr(chardev, param)

            uiutil.set_grid_row_visible(self.widget(widgetname), doshow)
            self.widget(widgetname).set_text(val or "-")

        def build_host_str(base):
            if (not chardev.supports_property(base + "_host") or
                not chardev.supports_property(base + "_port")):
                return ""

            host = getattr(chardev, base + "_host") or ""
            port = getattr(chardev, base + "_port") or ""

            ret = str(host)
            if port:
                ret += ":%s" % str(port)
            return ret

        char_type = chardev.virtual_device_type.capitalize()
        target_port = chardev.target_port
        dev_type = chardev.type or "pty"
        primary = hasattr(chardev, "virtmanager_console_dup")

        typelabel = ""
        if char_type == "serial":
            typelabel = _("Serial Device")
        elif char_type == "parallel":
            typelabel = _("Parallel Device")
        elif char_type == "console":
            typelabel = _("Console Device")
        elif char_type == "channel":
            typelabel = _("Channel Device")
        else:
            typelabel = _("%s Device") % char_type.capitalize()

        if target_port is not None and not show_target_type:
            typelabel += " %s" % (int(target_port) + 1)
        if primary:
            typelabel += " (%s)" % _("Primary Console")
        typelabel = "<b>%s</b>" % typelabel

        self.widget("char-type").set_markup(typelabel)
        self.widget("char-dev-type").set_text(dev_type)

        # Device type specific properties, only show if apply to the cur dev
        show_ui("source_host", build_host_str("source"))
        show_ui("bind_host", build_host_str("bind"))
        show_ui("source_path")
        show_ui("target_type")
        show_ui("target_name")

    def refresh_hostdev_page(self):
        hostdev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not hostdev:
            return

        devtype = hostdev.type
        pretty_name = None
        nodedev = lookup_nodedev(self.vm.conn, hostdev)
        if nodedev:
            pretty_name = nodedev.pretty_name()

        if not pretty_name:
            pretty_name = build_hostdev_label(hostdev)[0] or "-"

        devlabel = "<b>Physical %s Device</b>" % devtype.upper()
        self.widget("hostdev-title").set_markup(devlabel)
        self.widget("hostdev-source").set_text(pretty_name)

    def refresh_video_page(self):
        vid = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not vid:
            return

        no_default = not self.is_customize_dialog
        vmmAddHardware.populate_video_combo(self.vm,
            self.widget("video-model"),
            no_default=no_default)

        model = vid.model
        ram = vid.vram
        heads = vid.heads
        try:
            ramlabel = ram and "%d MB" % (int(ram) / 1024) or "-"
        except:
            ramlabel = "-"

        self.widget("video-ram").set_text(ramlabel)
        self.widget("video-heads").set_text(heads and str(heads) or "-")

        self.set_combo_entry("video-model", model,
                             label=vid.pretty_model(model))

    def refresh_watchdog_page(self):
        watch = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not watch:
            return

        model = watch.model
        action = watch.action

        self.set_combo_entry("watchdog-model", model)
        self.set_combo_entry("watchdog-action", action)

    def refresh_controller_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        type_label = virtinst.VirtualController.pretty_type(dev.type)
        model_label = dev.model
        if not model_label:
            model_label = _("Default")

        self.widget("controller-type").set_text(type_label)
        combo = self.widget("controller-model")
        uiutil.set_grid_row_visible(combo, True)

        model = combo.get_model()
        model.clear()
        if dev.type == virtinst.VirtualController.TYPE_USB:
            model.append(["default", "Default"])
            model.append(["ich9-ehci1", "USB 2"])
            model.append(["nec-xhci", "USB 3"])
            self.widget("config-remove").set_sensitive(False)
        if dev.type == virtinst.VirtualController.TYPE_SCSI:
            model.append(["default", "Default"])
            model.append(["virtio-scsi", "Virtio SCSI"])
        else:
            self.widget("config-remove").set_sensitive(True)

        self.set_combo_entry("controller-model", dev.model or "default")

    def refresh_filesystem_page(self):
        dev = self.get_hw_selection(HW_LIST_COL_DEVICE)
        if not dev:
            return

        self.fsDetails.set_dev(dev)
        self.fsDetails.update_fs_rows()

    def refresh_boot_page(self):
        # Refresh autostart
        try:
            # Older libvirt versions return None if not supported
            autoval = self.vm.get_autostart()
        except libvirt.libvirtError:
            autoval = None

        # Autostart
        autostart_chk = self.widget("config-autostart")
        enable_autostart = (autoval is not None)
        autostart_chk.set_sensitive(enable_autostart)
        autostart_chk.set_active(enable_autostart and autoval or False)

        show_kernel = not self.vm.is_container()
        show_init = self.vm.is_container()
        show_boot = (not self.vm.is_container() and not self.vm.is_xenpv())

        self.widget("boot-order-align").set_visible(show_boot)
        self.widget("boot-kernel-align").set_visible(show_kernel)
        self.widget("boot-init-align").set_visible(show_init)

        # Kernel/initrd boot
        kernel, initrd, dtb, args = self.vm.get_boot_kernel_info()
        expand = bool(kernel or dtb or initrd or args)

        def keep_text(wname, guestval):
            # If the user unsets kernel/initrd by unchecking the
            # 'enable kernel boot' box, we keep the previous values cached
            # in the text fields to allow easy switching back and forth.
            guestval = guestval or ""
            if self.get_text(wname) and not guestval:
                return
            self.widget(wname).set_text(guestval)

        keep_text("boot-kernel", kernel)
        keep_text("boot-initrd", initrd)
        keep_text("boot-dtb", dtb)
        keep_text("boot-kernel-args", args)
        if expand:
            # Only 'expand' if requested, so a refresh doesn't
            # magically unexpand the UI the user just touched
            self.widget("boot-kernel-expander").set_expanded(True)
        self.widget("boot-kernel-enable").set_active(expand)
        self.widget("boot-kernel-enable").toggled()

        # Only show dtb if it's supported
        arch = self.vm.get_arch() or ""
        show_dtb = (self.get_text("boot-dtb") or
            self.vm.get_hv_type() == "test" or
            "arm" in arch or "microblaze" in arch or "ppc" in arch)
        self.widget("boot-dtb-label").set_visible(show_dtb)
        self.widget("boot-dtb-box").set_visible(show_dtb)

        # <init> populate
        init = self.vm.get_init()
        self.widget("boot-init-path").set_text(init or "")

        # Boot menu populate
        menu = self.vm.get_boot_menu() or False
        self.widget("boot-menu").set_active(menu)
        self.repopulate_boot_list()


    ############################
    # Hardware list population #
    ############################

    def populate_disk_bus_combo(self, devtype, no_default):
        buslist     = self.widget("disk-bus")
        busmodel    = buslist.get_model()
        busmodel.clear()

        buses = []
        if devtype == virtinst.VirtualDisk.DEVICE_FLOPPY:
            buses.append(["fdc", "Floppy"])
        elif devtype == virtinst.VirtualDisk.DEVICE_CDROM:
            buses.append(["ide", "IDE"])
            if not self.vm.stable_defaults():
                buses.append(["scsi", "SCSI"])
        else:
            if self.vm.is_hvm():
                buses.append(["ide", "IDE"])
                if not self.vm.stable_defaults():
                    buses.append(["scsi", "SCSI"])
                    buses.append(["usb", "USB"])
            if self.vm.get_hv_type() in ["kvm", "test"]:
                buses.append(["sata", "SATA"])
                buses.append(["virtio", "Virtio"])
            if (self.vm.get_hv_type() == "kvm" and
                    self.vm.get_machtype() == "pseries"):
                buses.append(["spapr-vscsi", "sPAPR-vSCSI"])
            if self.vm.conn.is_xen() or self.vm.get_hv_type() == "test":
                buses.append(["xen", "Xen"])

        for row in buses:
            busmodel.append(row)
        if not no_default:
            busmodel.append([None, "default"])

    def populate_hw_list(self):
        hw_list_model = self.widget("hw-list").get_model()
        hw_list_model.clear()

        def add_hw_list_option(title, page_id, icon_name):
            hw_list_model.append([title, icon_name,
                                  Gtk.IconSize.LARGE_TOOLBAR,
                                  page_id, title])

        add_hw_list_option(_("Overview"), HW_LIST_TYPE_GENERAL, "computer")
        if not self.is_customize_dialog:
            if self.config.support_inspection:
                add_hw_list_option(_("OS information"),
                    HW_LIST_TYPE_INSPECTION, "computer")
            add_hw_list_option("Performance", HW_LIST_TYPE_STATS,
                               "utilities-system-monitor")
        add_hw_list_option("Processor", HW_LIST_TYPE_CPU, "device_cpu")
        add_hw_list_option("Memory", HW_LIST_TYPE_MEMORY, "device_mem")
        add_hw_list_option("Boot Options", HW_LIST_TYPE_BOOT, "system-run")

        self.repopulate_hw_list()

    def repopulate_hw_list(self):
        hw_list = self.widget("hw-list")
        hw_list_model = hw_list.get_model()

        currentDevices = []

        def dev_cmp(origdev, newdev):
            if isinstance(origdev, str):
                return False

            if origdev == newdev:
                return True

            if not origdev.get_root_xpath():
                return False

            return origdev.get_root_xpath() == newdev.get_root_xpath()

        def add_hw_list_option(idx, name, page_id, info, icon_name):
            hw_list_model.insert(idx, [name, icon_name,
                                       Gtk.IconSize.LARGE_TOOLBAR,
                                       page_id, info])

        def update_hwlist(hwtype, info, name, icon_name):
            """
            See if passed hw is already in list, and if so, update info.
            If not in list, add it!
            """
            currentDevices.append(info)

            insertAt = 0
            for row in hw_list_model:
                rowdev = row[HW_LIST_COL_DEVICE]
                if dev_cmp(rowdev, info):
                    # Update existing HW info
                    row[HW_LIST_COL_DEVICE] = info
                    row[HW_LIST_COL_LABEL] = name
                    row[HW_LIST_COL_ICON_NAME] = icon_name
                    return

                if row[HW_LIST_COL_TYPE] <= hwtype:
                    insertAt += 1

            # Add the new HW row
            add_hw_list_option(insertAt, name, hwtype, info, icon_name)

        # Populate list of disks
        for disk in self.vm.get_disk_devices():
            devtype = disk.device
            bus = disk.bus
            idx = disk.disk_bus_index

            icon = "drive-harddisk"
            if devtype == "cdrom":
                icon = "media-optical"
            elif devtype == "floppy":
                icon = "media-floppy"

            if disk.address.type == "spapr-vio":
                bus = "spapr-vscsi"

            label = prettyify_disk(devtype, bus, idx)

            update_hwlist(HW_LIST_TYPE_DISK, disk, label, icon)

        # Populate list of NICs
        for net in self.vm.get_network_devices():
            mac = net.macaddr

            update_hwlist(HW_LIST_TYPE_NIC, net,
                          "NIC %s" % mac[-9:], "network-idle")

        # Populate list of input devices
        for inp in self.vm.get_input_devices():
            inptype = inp.type

            icon = "input-mouse"
            if inptype == "tablet":
                label = _("Tablet")
                icon = "input-tablet"
            elif inptype == "mouse":
                label = _("Mouse")
            else:
                label = _("Input")

            update_hwlist(HW_LIST_TYPE_INPUT, inp, label, icon)

        # Populate list of graphics devices
        for gfx in self.vm.get_graphics_devices():
            update_hwlist(HW_LIST_TYPE_GRAPHICS, gfx,
                          _("Display %s") % gfx.pretty_type_simple(gfx.type),
                          "video-display")

        # Populate list of sound devices
        for sound in self.vm.get_sound_devices():
            update_hwlist(HW_LIST_TYPE_SOUND, sound,
                          _("Sound: %s" % sound.model), "audio-card")

        # Populate list of char devices
        for chardev in self.vm.get_char_devices():
            devtype = chardev.virtual_device_type
            port = chardev.target_port

            label = devtype.capitalize()
            if devtype in ["serial", "parallel"]:
                label += " %s" % (int(port) + 1)
            elif devtype == "channel":
                name = chardev.pretty_channel_name(chardev.target_name)
                if name:
                    label += " %s" % name

            update_hwlist(HW_LIST_TYPE_CHAR, chardev, label,
                          "device_serial")

        # Populate host devices
        for hostdev in self.vm.get_hostdev_devices():
            devtype = hostdev.type
            label = build_hostdev_label(hostdev)[1]

            if devtype == "usb":
                icon = "device_usb"
            else:
                icon = "device_pci"
            update_hwlist(HW_LIST_TYPE_HOSTDEV, hostdev, label, icon)

        # Populate redir devices
        for redirdev in self.vm.get_redirdev_devices():
            bus = redirdev.bus
            label = build_redir_label(redirdev)[1]

            if bus == "usb":
                icon = "device_usb"
            else:
                icon = "device_pci"
            update_hwlist(HW_LIST_TYPE_REDIRDEV, redirdev, label, icon)

        # Populate video devices
        for vid in self.vm.get_video_devices():
            update_hwlist(HW_LIST_TYPE_VIDEO, vid,
                          _("Video %s") % vid.pretty_model(vid.model),
                          "video-display")

        # Populate watchdog devices
        for watch in self.vm.get_watchdog_devices():
            update_hwlist(HW_LIST_TYPE_WATCHDOG, watch, _("Watchdog"),
                          "device_pci")

        # Populate controller devices
        for cont in self.vm.get_controller_devices():
            # skip USB2 ICH9 companion controllers
            if cont.model in ["ich9-uhci1", "ich9-uhci2", "ich9-uhci3"]:
                continue

            pretty_type = virtinst.VirtualController.pretty_type(cont.type)
            update_hwlist(HW_LIST_TYPE_CONTROLLER, cont,
                          _("Controller %s") % pretty_type,
                          "device_pci")

        # Populate filesystem devices
        for fs in self.vm.get_filesystem_devices():
            target = fs.target[:8]
            update_hwlist(HW_LIST_TYPE_FILESYSTEM, fs,
                          _("Filesystem %s") % target,
                          Gtk.STOCK_DIRECTORY)

        # Populate list of smartcard devices
        for sc in self.vm.get_smartcard_devices():
            update_hwlist(HW_LIST_TYPE_SMARTCARD, sc,
                          _("Smartcard"), "device_serial")

        # Populate list of TPM devices
        for tpm in self.vm.get_tpm_devices():
            update_hwlist(HW_LIST_TYPE_TPM, tpm,
                          _("TPM"), "device_cpu")

        # Populate list of RNG devices
        for rng in self.vm.get_rng_devices():
            update_hwlist(HW_LIST_TYPE_RNG, rng,
                          _("RNG"), "system-run")

        # Populate list of Panic devices
        for rng in self.vm.get_panic_devices():
            update_hwlist(HW_LIST_TYPE_PANIC, rng,
                          _("Panic Notifier"), "system-run")

        devs = range(len(hw_list_model))
        devs.reverse()
        for i in devs:
            _iter = hw_list_model.iter_nth_child(None, i)
            olddev = hw_list_model[i][HW_LIST_COL_DEVICE]

            # Existing device, don't remove it
            if type(olddev) is str or olddev in currentDevices:
                continue

            hw_list_model.remove(_iter)

    def repopulate_boot_list(self, bootdevs=None, dev_select=None):
        boot_list = self.widget("config-boot-list")
        boot_model = boot_list.get_model()
        old_order = [x[BOOT_DEV_TYPE] for x in boot_model]
        boot_model.clear()

        if bootdevs is None:
            bootdevs = self.vm.get_boot_device()

        boot_rows = {
            "hd" : ["hd", "Hard Disk", "drive-harddisk", False],
            "cdrom" : ["cdrom", "CDROM", "media-optical", False],
            "network" : ["network", "Network (PXE)", "network-idle", False],
            "fd" : ["fd", "Floppy", "media-floppy", False],
        }

        for dev in bootdevs:
            foundrow = None

            for key, row in boot_rows.items():
                if key == dev:
                    foundrow = row
                    del(boot_rows[key])
                    break

            if not foundrow:
                # Some boot device listed that we don't know about.
                foundrow = [dev, "Boot type '%s'" % dev,
                            "drive-harddisk", True]

            foundrow[BOOT_ACTIVE] = True
            boot_model.append(foundrow)

        # Append all remaining boot_rows that aren't enabled
        for dev in old_order:
            if dev in boot_rows:
                boot_model.append(boot_rows[dev])
                del(boot_rows[dev])

        for row in boot_rows.values():
            boot_model.append(row)

        boot_list.set_model(boot_model)
        selection = boot_list.get_selection()

        if dev_select:
            idx = 0
            for row in boot_model:
                if row[BOOT_DEV_TYPE] == dev_select:
                    break
                idx += 1

            boot_list.get_selection().select_path(str(idx))

        elif not selection.get_selected()[1]:
            # Set a default selection
            selection.select_path("0")

    def show_pair(self, basename, show):
        combo = self.widget(basename)
        label = self.widget(basename + "-title")

        combo.set_visible(show)
        label.set_visible(show)
