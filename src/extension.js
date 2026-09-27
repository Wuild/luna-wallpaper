import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {isDue} from './model.js';

export default class WallpaperExtension extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._background = new Gio.Settings({schema_id: 'org.gnome.desktop.background'});
        this._retryAt = 0;
        this._busy = false;
        this._syncButton();
        this._settings.connectObject('changed::show-panel-button', () => this._syncButton(), this);
        this._settings.connectObject('changed::request', () => {
            const action = this._settings.get_string('request').split(':')[0];
            if (['random', 'daily'].includes(action)) this._change(action);
        }, 'changed::interval', () => this._tick(), this);
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 60, () => {
            this._tick();
            return GLib.SOURCE_CONTINUE;
        });
        this._settings.set_string('status', 'Ready. Desktop and lock screen use the same wallpaper.');
        this._tick();
    }

    _syncButton() {
        if (!this._settings.get_boolean('show-panel-button')) {
            this._button?.destroy();
            this._button = this._title = null;
            return;
        }
        if (this._button) return;
        this._button = new PanelMenu.Button(0.0, 'Luna Wallpaper');
        this._button.add_child(new St.Icon({icon_name: 'preferences-desktop-wallpaper-symbolic', style_class: 'system-status-icon'}));
        this._title = new PopupMenu.PopupMenuItem('Luna - Wallpaper', {reactive: false});
        this._button.menu.addMenuItem(this._title);
        this._button.menu.addAction('Random wallpaper', () => this._change('random'));
        this._button.menu.addAction('Bing image of the day', () => this._change('daily'));
        this._button.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._button.menu.addAction('Wallpaper settings', () => this.openPreferences());
        Main.panel.addToStatusArea(this.uuid, this._button);
        if (this._busy) this._title.label.text = 'Downloading wallpaper…';
    }

    _tick() {
        if (isDue(Date.now() / 1000, this._settings.get_double('last-success'), this._settings.get_uint('interval'), this._retryAt))
            this._change(this._settings.get_string('rotation-mode'));
    }

    async _change(action) {
        if (this._busy || !this._settings) return;
        this._busy = true;
        const settings = this._settings;
        settings.set_string('status', 'Finding and downloading a wallpaper…');
        if (this._title) this._title.label.text = 'Downloading wallpaper…';
        const cancellable = new Gio.Cancellable();
        this._cancellable = cancellable;
        const config = {action, directory: GLib.build_filenamev([GLib.get_user_data_dir(), 'luna-wallpaper', 'images'])};
        for (const key of ['bing-market', 'query', 'current-url']) config[key] = settings.get_string(key);
        for (const key of ['providers', 'categories', 'recent-urls']) config[key] = settings.get_strv(key);
        let process;
        try {
            process = Gio.Subprocess.new(['python3', `${this.path}/worker.py`], Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
            this._process = process;
            this._deadline = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 180, () => {
                this._deadline = 0;
                process.force_exit();
                return GLib.SOURCE_REMOVE;
            });
            const output = await new Promise((resolve, reject) => {
                process.communicate_utf8_async(JSON.stringify(config), cancellable, (source, result) => {
                    try { resolve(source.communicate_utf8_finish(result)[1]); } catch (error) { reject(error); }
                });
            });
            if (cancellable.is_cancelled()) return;
            const result = output ? JSON.parse(output) : {ok: false, error: 'Wallpaper request timed out or the worker stopped'};
            if (!result.ok) throw new Error(result.error);
            const uri = Gio.File.new_for_path(result.path).get_uri();
            for (const key of ['picture-uri', 'picture-uri-dark', 'picture-options']) {
                if (!this._background.is_writable(key)) throw new Error('Your administrator has locked the desktop wallpaper settings');
            }
            this._background.delay();
            this._background.set_string('picture-uri', uri);
            this._background.set_string('picture-uri-dark', uri);
            this._background.set_string('picture-options', 'zoom');
            this._background.apply();
            settings.set_string('current-path', result.path);
            settings.set_string('current-url', result.url);
            settings.set_strv('recent-urls', [result.url, ...settings.get_strv('recent-urls').filter(url => url !== result.url)].slice(0, 100));
            settings.set_string('current-title', `${result.provider} · ${result.title}`);
            settings.set_string('current-source', result.source);
            settings.set_double('last-success', Date.now() / 1000);
            settings.set_string('status', 'Wallpaper updated for desktop and lock screen.');
            this._retryAt = 0;
            this._prune(result.path);
        } catch (error) {
            if (!cancellable.is_cancelled()) {
                settings.set_string('status', `Could not change wallpaper: ${error.message}`);
                this._retryAt = Date.now() / 1000 + 900;
            }
        } finally {
            if (this._settings === settings) {
                if (this._deadline) GLib.Source.remove(this._deadline);
                this._deadline = 0;
                this._process = null;
                this._cancellable = null;
                this._busy = false;
                if (this._title) this._title.label.text = 'Luna - Wallpaper';
            }
        }
    }

    _prune(currentPath) {
        try {
            const directory = Gio.File.new_for_path(GLib.path_get_dirname(currentPath));
            const enumerator = directory.enumerate_children('standard::name,time::modified', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
            const files = [];
            let info;
            while ((info = enumerator.next_file(null))) {
                if (/^[a-f0-9]{64}\.jpg$/.test(info.get_name()))
                    files.push({name: info.get_name(), time: info.get_attribute_uint64('time::modified')});
            }
            enumerator.close(null);
            files.sort((a, b) => b.time - a.time);
            for (const file of files.slice(20)) {
                const child = directory.get_child(file.name);
                if (child.get_path() !== currentPath) child.delete(null);
            }
        } catch { /* Cleanup must not turn a successful wallpaper update into an error. */ }
    }

    disable() {
        this._settings?.disconnectObject(this);
        if (this._timer) GLib.Source.remove(this._timer);
        if (this._deadline) GLib.Source.remove(this._deadline);
        this._cancellable?.cancel();
        this._process?.force_exit();
        this._button?.destroy();
        this._settings = this._background = this._button = this._title = null;
        this._cancellable = this._process = null;
        this._timer = this._deadline = 0;
        this._busy = false;
    }
}
