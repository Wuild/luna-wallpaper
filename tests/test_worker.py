import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'src' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

worker = module('worker', 'worker.py')
gdm = module('gdm', 'gdm-helper.py')

class Providers(unittest.TestCase):
    def test_bing_daily_ignores_categories_and_keywords(self):
        with patch.object(worker, 'api', return_value={'images': [{'url': '/image.jpg', 'copyright': 'Mountains'}]}) as api:
            results = worker.bing({'categories': ['city'], 'query': 'impossible'}, True)
        self.assertEqual(len(results), 1)
        self.assertEqual(api.call_args.args[1]['n'], 1)
        self.assertEqual(results[0]['url'], 'https://www.bing.com/image.jpg')

    def test_bing_random_filters_captions(self):
        with patch.object(worker, 'api', return_value={'images': [{'url': '/a', 'copyright': 'Ocean waves'}, {'url': '/b', 'copyright': 'City lights'}]}):
            self.assertEqual(worker.bing({'categories': ['ocean']})[0]['url'], 'https://www.bing.com/a')
            self.assertEqual(worker.bing({'categories': ['forest']}), [])

    def test_provider_failure_falls_back(self):
        with patch.object(worker.random, 'shuffle'), patch.object(worker, 'bing', side_effect=ValueError('Offline')), patch.object(worker, 'wallhaven', return_value=[{'url': 'https://example.com/image'}]):
            self.assertEqual(next(worker.candidates({'providers': ['bing', 'wallhaven']}))['url'], 'https://example.com/image')

    def test_avoid_current_image(self):
        with patch.object(worker.random, 'shuffle'), patch.object(worker, 'bing', return_value=[{'url': 'old'}, {'url': 'new'}]):
            self.assertEqual(next(worker.candidates({'providers': ['bing'], 'current-url': 'old'}))['url'], 'new')

    def test_unseen_images_precede_previously_used_images(self):
        with patch.object(worker.random, 'shuffle'), patch.object(worker, 'bing', return_value=[{'url': 'yesterday'}, {'url': 'unseen'}, {'url': 'current'}]):
            config = {'providers': ['bing'], 'current-url': 'current', 'recent-urls': ['current', 'yesterday']}
            self.assertEqual(next(worker.candidates(config))['url'], 'unseen')

    def test_exhausted_archive_uses_least_recent_image(self):
        with patch.object(worker.random, 'shuffle'), patch.object(worker, 'bing', return_value=[{'url': 'current'}, {'url': 'yesterday'}, {'url': 'oldest'}]):
            config = {'providers': ['bing'], 'current-url': 'current', 'recent-urls': ['current', 'yesterday', 'oldest']}
            self.assertEqual(next(worker.candidates(config))['url'], 'oldest')

    def test_no_providers_and_empty_results_are_errors(self):
        with self.assertRaisesRegex(ValueError, 'No matching'):
            worker.run({'providers': []})
        with patch.object(worker, 'bing', return_value=[]), self.assertRaisesRegex(ValueError, 'no matching'):
            worker.run({'providers': ['bing']})

    def test_non_https_and_private_addresses_rejected(self):
        for url in ['file:///etc/passwd', 'http://example.com', 'https://user:pass@example.com', 'https://example.com:8443']:
            with self.assertRaises(ValueError): worker.public_url(url)
        with patch.object(worker.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]), self.assertRaises(ValueError):
            worker.public_url('https://localhost/image.jpg')

    def test_invalid_image_does_not_create_wallpaper(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): worker.save_image(b'<html>not an image</html>', directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_valid_image_is_normalized(self):
        import gi
        gi.require_version('GdkPixbuf', '2.0')
        from gi.repository import GdkPixbuf
        image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 640, 360)
        image.fill(0x4477aaff)
        _, data = image.save_to_bufferv('png', [], [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(worker.save_image(bytes(data), directory))
            self.assertTrue(path.read_bytes().startswith(b'\xff\xd8'))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

class Gdm(unittest.TestCase):
    def test_interrupted_reapply_can_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / 'theme.gresource'; resource.write_bytes(b'original')
            state = Path(directory) / 'state'
            with patch.object(gdm, 'compile_resource', return_value=b'first'):
                gdm.apply(resource, state, b'one')
            original_write = gdm.atomic_write
            def interrupted(path, data, mode=0o644):
                if path == resource: raise OSError('interrupted before replacement')
                original_write(path, data, mode)
            with patch.object(gdm, 'compile_resource', return_value=b'second'), patch.object(gdm, 'atomic_write', side_effect=interrupted), self.assertRaises(OSError):
                gdm.apply(resource, state, b'two')
            gdm.restore(resource, state)
            self.assertEqual(resource.read_bytes(), b'original')

    def test_helper_normalizes_image_and_rejects_symlink(self):
        import gi
        gi.require_version('GdkPixbuf', '2.0')
        from gi.repository import GdkPixbuf
        image = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 640, 360)
        image.fill(0x4477aaff)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.png'
            image.savev(str(path), 'png', [], [])
            self.assertTrue(gdm.read_image(path).startswith(b'\xff\xd8'))
            link = Path(directory) / 'link.png'; link.symlink_to(path)
            with self.assertRaises(OSError): gdm.read_image(link)

    def test_apply_restore_and_external_update_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / 'theme.gresource'
            resource.write_bytes(b'original')
            state = Path(directory) / 'state'
            with patch.object(gdm, 'compile_resource', return_value=b'patched'):
                gdm.apply(resource, state, b'image')
            self.assertEqual(resource.read_bytes(), b'patched')
            resource.write_bytes(b'package update')
            with self.assertRaisesRegex(ValueError, 'outside Luna'): gdm.restore(resource, state)
            with patch.object(gdm, 'compile_resource'), self.assertRaisesRegex(ValueError, 'outside Luna'):
                gdm.apply(resource, state, b'image')
            resource.write_bytes(b'patched')
            gdm.restore(resource, state)
            self.assertEqual(resource.read_bytes(), b'original')
            self.assertFalse((state / 'state.json').exists())

    def test_compile_failure_leaves_system_and_backup_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / 'theme.gresource'
            resource.write_bytes(b'original')
            state = Path(directory) / 'state'
            with patch.object(gdm, 'compile_resource', side_effect=ValueError('unsupported')), self.assertRaises(ValueError):
                gdm.apply(resource, state, b'image')
            self.assertEqual(resource.read_bytes(), b'original')
            self.assertFalse(state.exists())

    def test_repeated_apply_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / 'theme.gresource'; resource.write_bytes(b'original')
            state = Path(directory) / 'state'
            with patch.object(gdm, 'compile_resource', side_effect=[b'first', b'second']):
                gdm.apply(resource, state, b'one'); gdm.apply(resource, state, b'two')
            gdm.restore(resource, state)
            self.assertEqual(resource.read_bytes(), b'original')

    def test_system_resource_rebuild_in_temporary_directory(self):
        source = Path('/usr/share/gnome-shell/gnome-shell-theme.gresource')
        if not source.exists(): self.skipTest('GNOME theme not installed')
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            rebuilt = Path(directory) / 'rebuilt.gresource'
            rebuilt.write_bytes(gdm.compile_resource(source.read_bytes(), b'image-fixture'))
            paths = subprocess.check_output(['gresource', 'list', str(rebuilt)], text=True)
            self.assertIn('/org/gnome/shell/theme/luna-wallpaper.jpg', paths)
            css = subprocess.check_output(['gresource', 'extract', str(rebuilt), '/org/gnome/shell/theme/gnome-shell-dark.css'], text=True)
            self.assertIn('resource:///org/gnome/shell/theme/luna-wallpaper.jpg', css)

if __name__ == '__main__': unittest.main()
