import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const HELPER = '/usr/libexec/luna-greeter-policy-sync';
const STATE = '/var/lib/luna-greeter/state.json';
const IMAGE = '/var/lib/luna-greeter/current.jpg';
const POLICY_KEYS = [
    'interval', 'rotation-mode', 'providers', 'categories', 'bing-market',
    'query', 'last-success', 'current-url', 'recent-urls', 'current-path',
];

export function adoptGreeterWallpaper(settings, background) {
    try {
        if (!GLib.file_test(STATE, GLib.FileTest.IS_REGULAR) ||
            !GLib.file_test(IMAGE, GLib.FileTest.IS_REGULAR))
            return false;
        const [ok, contents] = GLib.file_get_contents(STATE);
        if (!ok)
            return false;
        const state = JSON.parse(new TextDecoder().decode(contents));
        if (!Number.isFinite(state['last-success']) ||
            state['last-success'] <= settings.get_double('last-success'))
            return false;
        const uri = Gio.File.new_for_path(IMAGE).get_uri();
        background.delay();
        background.set_string('picture-uri', uri);
        background.set_string('picture-uri-dark', uri);
        background.set_string('picture-options', 'zoom');
        background.apply();
        settings.delay();
        settings.set_string('current-path', IMAGE);
        settings.set_string('current-url', state['current-url'] ?? '');
        settings.set_strv('recent-urls', Array.isArray(state['recent-urls']) ? state['recent-urls'] : []);
        settings.set_string('current-title', state.title ?? 'Scheduled login wallpaper');
        settings.set_string('current-source', state.source ?? '');
        settings.set_double('last-success', state['last-success']);
        settings.set_string('status', 'Adopted the wallpaper changed while no user was logged in.');
        settings.apply();
        return true;
    } catch {
        return false;
    }
}

export class GreeterPolicySync {
    constructor(settings) {
        this._settings = settings;
        this._source = 0;
        this._busy = false;
        this._dirty = false;
        for (const key of POLICY_KEYS)
            settings.connectObject(`changed::${key}`, () => this.schedule(), this);
        this.schedule();
    }

    schedule() {
        if (!this._settings || !GLib.file_test(HELPER, GLib.FileTest.IS_EXECUTABLE))
            return;
        this._dirty = true;
        if (this._source || this._busy)
            return;
        this._source = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._source = 0;
            this._flush();
            return GLib.SOURCE_REMOVE;
        });
    }

    async _flush() {
        if (!this._settings || this._busy)
            return;
        this._busy = true;
        this._dirty = false;
        const settings = this._settings;
        const policy = {
            interval: settings.get_uint('interval'),
            'rotation-mode': settings.get_string('rotation-mode'),
            providers: settings.get_strv('providers'),
            categories: settings.get_strv('categories'),
            'bing-market': settings.get_string('bing-market'),
            query: settings.get_string('query'),
            'last-success': settings.get_double('last-success'),
            'current-url': settings.get_string('current-url'),
            'recent-urls': settings.get_strv('recent-urls'),
        };
        const path = GLib.build_filenamev([
            GLib.get_user_runtime_dir(), 'luna-greeter-wallpaper-policy.json',
        ]);
        try {
            GLib.file_set_contents(path, JSON.stringify(policy));
            GLib.chmod(path, 0o600);
            const argv = ['pkexec', HELPER, path];
            const image = settings.get_string('current-path');
            if (image && GLib.file_test(image, GLib.FileTest.IS_REGULAR))
                argv.push(image);
            const process = Gio.Subprocess.new(argv,
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE);
            await new Promise(resolve => process.wait_async(null, (source, result) => {
                try { source.wait_finish(result); } catch { /* Retried on the next change. */ }
                resolve();
            }));
        } catch { /* Missing PolicyKit/session integration must not break wallpaper. */ }
        finally {
            try { Gio.File.new_for_path(path).delete(null); } catch { /* best effort */ }
            this._busy = false;
            if (this._dirty)
                this.schedule();
        }
    }

    destroy() {
        this._settings?.disconnectObject(this);
        if (this._source)
            GLib.Source.remove(this._source);
        this._settings = null;
        this._source = 0;
        this._dirty = false;
    }
}
