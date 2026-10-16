import asyncio
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import tomlkit
from backend.config import read_config, collect_icon_updates, apply_icon_updates, load_site, download_icon
from backend.main import LiveSite, initial_document, seconds_until_icon_refresh


def config_text(items):
    return '[[sections]]\ntitle = "Public"\n' + ''.join(
        '\n[[sections.items]]\nname = "' + name + '"\nurl = "https://example.com"\n' +
        (f'uri = "{uri}"\n' if uri is not None else '') for name, uri in items
    )


class IconTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'config.toml'

    def test_missing_owned_and_custom_uris(self):
        self.path.write_text(config_text([('Missing', None), ('Owned', '/icons/services/Owned.ico'), ('Manual', 'custom.svg'), ('Failed', 'Failed.png')]), encoding='utf-8')
        read_config(self.path, self.root)
        with patch('backend.config.download_icon', side_effect=lambda url, name, directory: None if name == 'Failed' else name + '.png') as fetch:
            original, updates = collect_icon_updates(self.path, self.root)
        self.assertEqual({call.args[1] for call in fetch.call_args_list}, {'Missing', 'Owned', 'Failed'})
        apply_icon_updates(self.path, original, updates)
        items = read_config(self.path, self.root).sections[0].items
        self.assertEqual([item.uri for item in items], ['Missing.png', 'Owned.png', 'custom.svg', ''])
        self.assertNotIn('uri', tomlkit.parse(self.path.read_text())['sections'][0]['items'][3])
        self.assertNotIn('error', load_site(self.path, self.root)['sections'][0]['items'][0])

    def test_failed_missing_uri_stays_missing(self):
        self.path.write_text(config_text([('Missing', None)]), encoding='utf-8')
        with patch('backend.config.download_icon', return_value=None):
            original, updates = collect_icon_updates(self.path, self.root)
        apply_icon_updates(self.path, original, updates)
        self.assertNotIn('uri', tomlkit.parse(self.path.read_text())['sections'][0]['items'][0])

    def test_existing_icon_migrates_without_losing_manual_choice(self):
        self.path.write_text(config_text([('Manual', 'custom.svg')]).replace('uri =', 'icon ='), encoding='utf-8')
        self.assertEqual(read_config(self.path, self.root).sections[0].items[0].uri, 'custom.svg')
        content = self.path.read_text()
        self.assertIn('uri = "custom.svg"', content)
        self.assertNotIn('icon =', content)

    def test_new_edit_is_not_overwritten(self):
        self.path.write_text(config_text([('Before', None)]), encoding='utf-8')
        original = self.path.read_text()
        edited = config_text([('After', 'manual.svg')])
        self.path.write_text(edited, encoding='utf-8')
        self.assertIsNone(apply_icon_updates(self.path, original, [(0, 0, 'Before.png')]))
        self.assertEqual(self.path.read_text(), edited)

    def test_image_signature_overrides_wrong_mime_and_suffix(self):
        from email.message import Message
        from io import BytesIO
        class Response(BytesIO):
            def __init__(self, data, mime, url):
                super().__init__(data)
                self.headers = Message()
                self.headers['Content-Type'] = mime
                self.url = url
        with patch('backend.config.urlopen', side_effect=[
            Response(b'<html></html>', 'text/html', 'https://example.com'),
            Response(b'\x89PNG\r\n\x1a\nimage', 'text/plain', 'https://example.com/favicon.ico'),
        ]):
            self.assertEqual(download_icon('https://example.com', 'Name', self.root), 'Name.png')
        self.assertTrue((self.root / 'Name.png').is_file())


class ScheduleTests(unittest.TestCase):
    def test_beijing_one_am(self):
        tz = timezone(timedelta(hours=8))
        self.assertEqual(seconds_until_icon_refresh(datetime(2026, 10, 16, 0, 59, 59, tzinfo=tz)), 1)
        self.assertEqual(seconds_until_icon_refresh(datetime(2026, 10, 16, 1, tzinfo=tz)), 86400)
        self.assertEqual(seconds_until_icon_refresh(datetime(2026, 10, 15, 16, 59, 59, tzinfo=timezone.utc)), 1)


class LiveIconTests(unittest.IsolatedAsyncioTestCase):
    async def test_inflight_requests_are_queued(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'config.toml'
            path.write_text(config_text([('Card', None)]), encoding='utf-8')
            live = LiveSite(root, path)
            live.refresh()
            started, release = threading.Event(), threading.Event()
            calls = []
            def collect(path, root):
                calls.append(1)
                started.set()
                release.wait(5)
                return path.read_text(encoding='utf-8'), [(0, 0, 'Card.png')]
            with patch('backend.main.collect_icon_updates', side_effect=collect):
                live.queue_icon_download()
                await asyncio.to_thread(started.wait, 3)
                live.queue_icon_download()
                release.set()
                await asyncio.wait_for(live.icon_download, 5)
            self.assertEqual(len(calls), 2)
            self.assertEqual(live.known_config, path.read_text(encoding='utf-8'))

    async def test_upload_publishes_without_refetch_and_config_edit_refetches(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'config.toml'
            path.write_text(config_text([('Card', 'manual.svg')]), encoding='utf-8')
            live = LiveSite(root, path)
            live.refresh()
            live.remember_config()
            with patch.object(live, 'queue_icon_download') as queue:
                watcher = asyncio.create_task(live.watch())
                try:
                    await asyncio.sleep(.9)
                    before = live.revision
                    icons = root / 'frontend/icons/services'
                    icons.mkdir(parents=True)
                    (icons / 'manual.svg').write_text('<svg/>')
                    await asyncio.sleep(1.2)
                    self.assertGreater(live.revision, before)
                    queue.assert_not_called()
                    path.write_text(config_text([('Edited', None)]), encoding='utf-8')
                    await asyncio.sleep(1.2)
                    queue.assert_called_once()
                    # 保存相同内容也可手动触发一轮重抓。
                    queue.reset_mock()
                    path.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
                    await asyncio.sleep(1.2)
                    queue.assert_called_once()
                finally:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)


class FallbackTests(unittest.TestCase):
    def test_links_are_present_without_javascript_and_colors_cross_sections(self):
        items = [{'name': '<Card>', 'url': 'https://example.com/?a=1&b=2', 'type': 'link'} for _ in range(4)]
        sections = [{'title': 'One', 'visibility': 'public', 'items': items}, {'title': 'Two', 'visibility': 'public', 'items': items}]
        data = {'site': {'appearance': {'title': 'Title', 'kicker': 'ACM', 'description': ''}, 'sections': sections}, 'revision': '1', 'visit_count': 0}
        source = initial_document(Path('frontend/index.html').read_text(), data)
        self.assertEqual(source.count('class="nav-card '), 8)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', source)
        self.assertIn('&lt;Card&gt;', source)
        import re
        colors = re.findall(r'--accent:(#[0-9a-f]+)', source)
        self.assertEqual(colors[:3], colors[5:])
        self.assertNotEqual(colors[0], colors[4])


if __name__ == '__main__':
    unittest.main()
