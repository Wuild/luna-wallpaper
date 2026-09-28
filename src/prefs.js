import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';
import {INTERVALS, nextLabel} from './model.js';

export default class WallpaperPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        window.set_default_size(760, 850);
        window.title = 'Wallpaper settings';
        const page = new Adw.PreferencesPage({title: 'Wallpaper', icon_name: 'preferences-desktop-wallpaper-symbolic'});
        window.add(page);
        const appearance = new Adw.PreferencesGroup({title: 'Panel'});
        page.add(appearance);
        const showButton = new Adw.SwitchRow({title: 'Show panel button', subtitle: 'Desktop’s Change wallpaper menu remains available when the button is hidden.'});
        settings.bind('show-panel-button', showButton, 'active', Gio.SettingsBindFlags.DEFAULT);
        appearance.add(showButton);
        const current = new Adw.PreferencesGroup({title: 'Your wallpaper', description: 'Applied to both desktop themes and the GNOME lock screen.'});
        page.add(current);
        const preview = new Gtk.Picture({height_request: 210, can_shrink: true, content_fit: Gtk.ContentFit.CONTAIN});
        current.add(preview);
        const title = new Adw.ActionRow({use_markup: false, title: 'No wallpaper selected yet'});
        current.add(title);
        const source = new Gtk.LinkButton({label: 'View source', valign: Gtk.Align.CENTER});
        title.add_suffix(source);
        const status = new Adw.ActionRow({use_markup: false, title: 'Status'});
        current.add(status);
        const actions = new Adw.ActionRow({use_markup: false, title: 'Change now'});
        for (const [label, action] of [['Random wallpaper', 'random'], ['Bing today', 'daily']]) {
            const button = new Gtk.Button({label, valign: Gtk.Align.CENTER});
            button.connect('clicked', () => settings.set_string('request', `${action}:${GLib.uuid_string_random()}`));
            actions.add_suffix(button);
        }
        current.add(actions);
        const update = () => {
            const path = settings.get_string('current-path');
            if (path && GLib.file_test(path, GLib.FileTest.IS_REGULAR)) preview.set_filename(path);
            title.title = settings.get_string('current-title') || 'No wallpaper selected yet';
            const url = settings.get_string('current-source');
            source.visible = /^https:\/\//.test(url);
            if (source.visible) source.uri = url;
            status.subtitle = settings.get_string('status');
        };
        update();
        const providers = new Adw.PreferencesGroup({title: 'Providers', description: 'Random mode tries the selected providers in a shuffled order. Bing today always uses Bing.'});
        page.add(providers);
        this._check(providers, settings, 'providers', 'bing', 'Bing', 'Daily photograph and up to eight recent images. Random avoids repeats until that pool is exhausted.');
        this._check(providers, settings, 'providers', 'wallhaven', 'Wallhaven', 'Random general-category wallpapers, filtered to SFW, at least 1920 × 1080.');
        this._entry(providers, settings, 'bing-market', 'Bing region', 'For example en-US, en-GB, sv-SE or de-DE');
        const categories = new Adw.PreferencesGroup({title: 'Categories', description: 'Select any combination, or leave all off for any category. Bing random matches captions; Bing today ignores filters.'});
        page.add(categories);
        for (const [value, label] of Object.entries({nature: 'Nature', mountains: 'Mountains', ocean: 'Ocean and beaches', forest: 'Forests', animals: 'Animals', city: 'Cities and architecture', space: 'Space', abstract: 'Abstract'}))
            this._check(categories, settings, 'categories', value, label);
        this._entry(categories, settings, 'query', 'Extra keywords', 'Optional search terms, such as aurora or Sweden');
        const rotation = new Adw.PreferencesGroup({title: 'Automatic changes', description: 'Runs while your session is active. Missed changes run when the extension resumes; failed requests retry after 15 minutes.'});
        page.add(rotation);
        const interval = new Adw.ComboRow({use_markup: false, title: 'Change wallpaper', model: Gtk.StringList.new(['Manually', 'Every hour', 'Every 6 hours', 'Every 12 hours', 'Every day', 'Every week']), selected: Math.max(0, INTERVALS.indexOf(settings.get_uint('interval')))});
        interval.connect('notify::selected', () => settings.set_uint('interval', INTERVALS[interval.selected]));
        rotation.add(interval);
        const mode = new Adw.ComboRow({use_markup: false, title: 'Scheduled image', model: Gtk.StringList.new(['Bing image of the day', 'Random from selected providers']), selected: settings.get_string('rotation-mode') === 'random' ? 1 : 0});
        mode.connect('notify::selected', () => settings.set_string('rotation-mode', mode.selected ? 'random' : 'daily'));
        rotation.add(mode);
        const next = new Adw.ActionRow({use_markup: false, title: 'Schedule'});
        rotation.add(next);
        const refreshNext = () => { next.subtitle = nextLabel(settings.get_double('last-success'), settings.get_uint('interval')); };
        settings.connectObject('changed::last-success', refreshNext,
            'changed::interval', refreshNext, window);
        refreshNext();
        const gdm = new Adw.PreferencesGroup({title: 'GDM login screen', description: 'System-wide background for all users. Applying or restoring requires administrator authentication. Changes appear the next time GDM starts. Automatic rotation affects desktop and lock screen only. Applying from Devkit also changes the host login screen.'});
        page.add(gdm);
        const gdmRow = new Adw.ActionRow({use_markup: false, title: 'Login wallpaper', subtitle: 'Uses the current downloaded wallpaper. Includes a backup and restore operation.'});
        gdm.add(gdmRow);
        const gdmStatus = new Adw.ActionRow({use_markup: false, title: 'GDM status', subtitle: 'Not changed by Luna in this preferences session.'});
        gdm.add(gdmStatus);
        const buttons = [];
        for (const [label, action] of [['Apply current', 'apply'], ['Restore original', 'restore']]) {
            const button = new Gtk.Button({label, valign: Gtk.Align.CENTER});
            buttons.push(button);
            button.connect('clicked', async () => {
                const path = settings.get_string('current-path');
                if (action === 'apply' && !path) { gdmStatus.subtitle = 'Choose a wallpaper first.'; return; }
                for (const b of buttons) b.sensitive = false;
                gdmStatus.subtitle = 'Waiting for administrator authorization…';
                try {
                    const argv = ['pkexec', '/usr/bin/python3', `${this.path}/gdm-helper.py`, action];
                    if (action === 'apply') argv.push(path);
                    const process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
                    const [out, err] = await new Promise((resolve, reject) => process.communicate_utf8_async(null, null, (p, res) => {
                        try { const [, stdout, stderr] = p.communicate_utf8_finish(res); resolve([stdout, stderr]); } catch (e) { reject(e); }
                    }));
                    if (!process.get_successful()) throw new Error(err.trim() || 'Authorization cancelled or helper failed.');
                    gdmStatus.subtitle = out.trim();
                } catch (e) { gdmStatus.subtitle = e.message; }
                finally { for (const b of buttons) b.sensitive = true; }
            });
            gdmRow.add_suffix(button);
        }
        const changed = settings.connect('changed', () => { update(); refreshNext(); });
        window.connect('close-request', () => { settings.disconnect(changed); return false; });
    }

    _entry(group, settings, key, title, subtitle) {
        const row = new Adw.EntryRow({title, text: settings.get_string(key), tooltip_text: subtitle});
        row.connect('changed', () => settings.set_string(key, row.text));
        group.add(row);
    }

    _check(group, settings, key, value, title, subtitle = '') {
        const row = new Adw.SwitchRow({use_markup: false, title, subtitle, active: settings.get_strv(key).includes(value)});
        row.connect('notify::active', () => {
            const values = new Set(settings.get_strv(key));
            if (row.active) values.add(value); else values.delete(value);
            settings.set_strv(key, [...values]);
        });
        group.add(row);
    }
}
