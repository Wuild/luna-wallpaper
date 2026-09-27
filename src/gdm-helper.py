"""Explicit, authenticated GDM theme update for GNOME 50.
No polkit bypass, service restart, arbitrary commands or arbitrary output paths.
The original resource is retained, and package-manager changes are detected.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

RESOURCE = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
STATE = Path('/var/lib/luna-wallpaper')
PREFIX = '/org/gnome/shell/theme'
IMAGE_RESOURCE = PREFIX + '/luna-wallpaper.jpg'
MAX_IMAGE = 25 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode=0o644):
    fd, name = tempfile.mkstemp(prefix='.luna-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_image(path):
    # Refuse FIFOs, devices, symlinks and oversized files before decoding.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_IMAGE:
            raise ValueError('Wallpaper must be a regular image file smaller than 25 MB')
        data = stream.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise ValueError('Wallpaper is too large')
    import gi
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import GdkPixbuf
    loader = GdkPixbuf.PixbufLoader.new()
    oversized = []
    def size_prepared(obj, width, height):
        if width * height > 80_000_000 or width > 20000 or height > 20000:
            oversized.append(True)
            obj.set_size(1, 1)
    loader.connect('size-prepared', size_prepared)
    loader.write(data)
    loader.close()
    pixbuf = loader.get_pixbuf()
    if oversized or pixbuf is None:
        raise ValueError('Unsupported image dimensions')
    ok, encoded = pixbuf.save_to_bufferv('jpeg', ['quality'], ['95'])
    if not ok:
        raise ValueError('Could not encode wallpaper')
    return bytes(encoded)


def compile_resource(original, image):
    with tempfile.TemporaryDirectory(prefix='luna-gdm-') as tmp:
        directory = Path(tmp)
        source = directory / 'original.gresource'
        source.write_bytes(original)
        paths = subprocess.check_output(['gresource', 'list', str(source)], text=True).splitlines()
        root = ET.Element('gresources')
        groups = {}
        matched = 0
        for index, path in enumerate(paths):
            prefix, _, alias = path.rpartition('/')
            if prefix not in groups:
                groups[prefix] = ET.SubElement(root, 'gresource', prefix=prefix)
            data = subprocess.check_output(['gresource', 'extract', str(source), path])
            if prefix == PREFIX and alias.startswith('gnome-shell') and alias.endswith('.css'):
                text = data.decode('utf-8')
                if '#lockDialogGroup' not in text:
                    raise ValueError('Unsupported GNOME theme: login background selector is absent')
                text += '\n/* Luna Wallpaper: generated login background */\n#lockDialogGroup { background-color: #202020; background-image: url("resource://' + IMAGE_RESOURCE + '"); background-size: cover; background-position: center; }\n'
                data = text.encode()
                matched += 1
            filename = f'asset-{index}'
            (directory / filename).write_bytes(data)
            ET.SubElement(groups[prefix], 'file', alias=alias).text = filename
        if not matched:
            raise ValueError('Unsupported GNOME resource: no login stylesheet found')
        (directory / 'wallpaper.jpg').write_bytes(image)
        ET.SubElement(groups[PREFIX], 'file', alias='luna-wallpaper.jpg').text = 'wallpaper.jpg'
        manifest = directory / 'theme.xml'
        ET.ElementTree(root).write(manifest, encoding='utf-8', xml_declaration=True)
        output = directory / 'theme.gresource'
        subprocess.run(['glib-compile-resources', str(manifest), '--sourcedir', str(directory), '--target', str(output)], check=True)
        subprocess.run(['gresource', 'list', str(output)], check=True, stdout=subprocess.DEVNULL)
        return output.read_bytes()


def apply(resource, state, image):
    backup = state / 'original.gresource'
    manifest = state / 'state.json'
    current = resource.read_bytes()
    if manifest.exists():
        metadata = json.loads(manifest.read_text())
        if digest(current) not in (metadata['installed'], metadata['original'], metadata.get('previous')):
            raise ValueError('The system theme changed outside Luna (possibly a GNOME update). Refusing to overwrite it. See README recovery instructions.')
        original = backup.read_bytes()
        if digest(original) != metadata['original']:
            raise ValueError('The original theme backup is damaged; refusing to continue')
    else:
        original = current
    # Build and validate completely before writing the system resource.
    patched = compile_resource(original, image)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not manifest.exists():
        atomic_write(backup, original, 0o600)
    # Record the intended installed hash first so an interrupted write is recoverable.
    metadata = {'original': digest(original), 'installed': digest(patched), 'previous': digest(current)}
    atomic_write(manifest, json.dumps(metadata).encode(), 0o600)
    atomic_write(resource, patched)


def restore(resource, state):
    manifest = state / 'state.json'
    if not manifest.exists():
        raise ValueError('No Luna GDM backup exists; nothing to restore')
    metadata = json.loads(manifest.read_text())
    if digest(resource.read_bytes()) not in (metadata['installed'], metadata['original'], metadata.get('previous')):
        raise ValueError('The system theme changed outside Luna. Refusing to restore an outdated backup. See README recovery instructions.')
    original = (state / 'original.gresource').read_bytes()
    if digest(original) != metadata['original']:
        raise ValueError('The original theme backup is damaged')
    atomic_write(resource, original)
    manifest.unlink()
    (state / 'original.gresource').unlink()


def main():
    if os.geteuid() != 0:
        raise ValueError('Administrator authentication is required (run through pkexec)')
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action not in ('apply', 'restore') or len(sys.argv) != (3 if action == 'apply' else 2):
        raise ValueError('Usage: gdm-helper.py apply IMAGE | restore')
    if not RESOURCE.is_file() or RESOURCE.is_symlink():
        raise ValueError('This system does not use the supported GNOME Shell theme resource')
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action == 'apply':
            apply(RESOURCE, STATE, read_image(sys.argv[2]))
        else:
            restore(RESOURCE, STATE)
    # Match the distro's SELinux labels after atomic replacement, if enabled.
    if Path('/usr/sbin/restorecon').exists():
        subprocess.run(['/usr/sbin/restorecon', str(RESOURCE)], check=True)
    print('Login wallpaper ' + ('applied' if action == 'apply' else 'restored') + '. Takes effect when GDM next starts; your session was not restarted.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
