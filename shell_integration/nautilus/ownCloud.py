#!/usr/bin/python3

import os
import urllib
import socket

from gi.repository import GObject, Nautilus


class ownCloudExtension(
        GObject.GObject,
        Nautilus.ColumnProvider,
        Nautilus.InfoProvider,
        Nautilus.MenuProvider):

    nautilusVFSFile_table = {}
    registered_paths = {}
    remainder = ''
    connected = False
    watch_id = 0

    def __init__(self):
        self.file_cache = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connectToOwnCloud()
        if not self.connected:
            # try again in 5 seconds - attention, logic inverted!
            GObject.timeout_add(5000, self.connectToOwnCloud)

    def port(self):
        return 34001  # Fixme, read from config file.

    def connectToOwnCloud(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect(("localhost", self.port()))
            self.sock.settimeout(5)
            self.connected = True
            self.watch_id = GObject.io_add_watch(
                self.sock,
                GObject.IO_IN,
                self.handle_notify
            )
        except socket.error as msg:
            print "Connect could not be established, try again later!"
            print msg
            self.sock.close()
        return not self.connected

    def sendCommand(self, cmd):
        if self.connected:
            try:
                self.sock.send(cmd+"\n")
            except socket.error as msg:
                print "Sending failed."
                print msg
                GObject.source_remove(self.watch_id)
                self.connected = False
                GObject.timeout_add(5000, self.connectToOwnCloud)

    def find_item_for_file(self, path):
        if path in self.nautilusVFSFile_table:
            return self.nautilusVFSFile_table[path]
        else:
            return None

    def askForOverlay(self, f):
        if os.path.isdir(f):
            self.sendCommand("RETRIEVE_FOLDER_STATUS:"+f)
        if os.path.isfile(f):
            self.sendCommand("RETRIEVE_FILE_STATUS:"+f)

    def invalidate_items_underneath(self, path):
        update_items = []
        for p in self.nautilusVFSFile_table:
            if p == path or p.startswith(path):
                item = self.nautilusVFSFile_table[p]
                update_items.append(item)

        for item in update_items:
            item.invalidate_extension_info()
            # self.update_file_info(item)

    # Handles a single line of server respoonse and sets the emblem
    def handle_server_response(self, l):
        Emblems = {
            'OK': 'oC_ok',
            'SYNC': 'oC_sync',
            'NEW': 'oC_sync',
            'IGNORE': 'oC_warn',
            'ERROR': 'oC_error',
            'OK+SWM': 'oC_ok_shared',
            'SYNC+SWM': 'oC_sync_shared',
            'NEW+SWM': 'oC_sync_shared',
            'IGNORE+SWM': 'oC_warn_shared',
            'ERROR+SWM': 'oC_error_shared',
            'NOP': 'oC_error'
        }

        print "Server response: "+l
        parts = l.split(':')
        if len(parts) > 0:
            action = parts[0]

            # file = parts[1]
            # print "Action for " + file + ": "+parts[0]
            if action == 'STATUS':
                self.file_cache[parts[2]] = parts[1]
                emblem = Emblems[parts[1]]
                if emblem:
                    item = self.find_item_for_file(parts[2])
                    if item:
                        item.add_emblem(emblem)

            elif action == 'UPDATE_VIEW' and parts[1] in self.registered_paths:
                self.invalidate_items_underneath(parts[1])
            elif action == 'REGISTER_PATH':
                self.registered_paths[parts[1]] = 1
                print self.registered_paths
                self.invalidate_items_underneath(parts[1])
            elif action == 'UNREGISTER_PATH':
                del self.registered_paths[parts[1]]
                self.invalidate_items_underneath(parts[1])

        # check if there are non pathes any more, if so, its usual
        # that mirall went away. Try reconnect.
        if not self.registered_paths:
            self.sock.close()
            self.connected = False
            GObject.source_remove(self.watch_id)
            GObject.timeout_add(5000, self.connectToOwnCloud)

    # notify is the raw answer from the socket
    def handle_notify(self, source, condition):
        data = source.recv(1024)
        # prepend the remaining data from last call
        if len(self.remainder) > 0:
            data = self.remainder+data
            self.remainder = ''

        if len(data) > 0:
            # remember the remainder for next round
            lastNL = data.rfind('\n')
            if lastNL > -1 and lastNL < len(data):
                self.remainder = data[lastNL+1:]
                data = data[:lastNL]

            for l in data.split('\n'):
                self.handle_server_response(l)
        else:
            return False

        return True  # run again

    def get_local_path(self, path):
        return path.replace("file://", "")

    def update_file_info(self, item):
        if item.get_uri_scheme() != 'file':
            return

        filename = urllib.unquote(item.get_uri()[7:])
        self.file_cache = {}
        for reg_path in self.registered_paths:
            if filename.startswith(reg_path):
                self.nautilusVFSFile_table[filename] = item
            self.askForOverlay(filename)
            break

    def advanced_sharing_menu(self, window, f):
        self.sendCommand('SHARE_DIALOG:'+f)

    def get_file_items(self, window, files):
        # If the user has selected multiple files, do not show the menu
        if len(files) != 1:
            return
        f = str(files[0].get_location().get_path())
        # Have we got data from the backend? is it ok to share?

        if (f not in self.file_cache or
                self.file_cache[f] not in ['OK', 'OK+SWM']):
            print 'FAIL', f
            print self.file_cache
            return

        menu = Nautilus.MenuItem(
            name='OwnCloudMenuProvider::ownCloud',
            label='ownCloud',
            tip='Share with ownCloud',
            icon='/usr/share/icons/hicolor/32x32/apps/owncloud.png'
        )

        submenu = Nautilus.Menu()
        menu.set_submenu(submenu)

        sub_menuitem = Nautilus.MenuItem(
            name='OwnCloudMenuProvider::ShareLink',
            label='Share Link',
            tip='Copy share link to clipboard',
            icon='/home/azelphur/ownCloud-share-tools/link.png'
        )
        submenu.append_item(sub_menuitem)
        sub_menuitem = Nautilus.MenuItem(
            name='OwnCloudMenuProvider::AdvancedSharing',
            label='Advanced Sharing',
            tip='Open advanced sharing dialog',
            icon='/home/azelphur/ownCloud-share-tools/share.png'
        )
        sub_menuitem.connect('activate', self.advanced_sharing_menu, f)
        submenu.append_item(sub_menuitem)
        sub_menuitem = Nautilus.MenuItem(
            name='OwnCloudMenuProvider::ViewOnline',
            label='View Online',
            tip='View file in web browser',
            icon='/home/azelphur/ownCloud-share-tools/viewonline.png'
        )
        submenu.append_item(sub_menuitem)
        return menu,
