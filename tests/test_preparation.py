"""Preparation ownership and atomic cache behavior across application instances."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from ktvibes import cache, worker


async def test_video_tasks_are_owned_by_each_worker(tmp_path):
    seen = []
    prepared = asyncio.Event()

    async def prepare(state, folder, item, videos):
        seen.append(videos)
        item['status'] = 'ready'
        if len(seen) == 2:
            prepared.set()

    states = [SimpleNamespace(wake=asyncio.Event(), upcoming=[{'status': 'queued'}]) for _ in range(2)]
    with patch.object(worker, 'prepare_song', prepare):
        tasks = [asyncio.create_task(worker.run(state, tmp_path)) for state in states]
        try:
            await asyncio.wait_for(prepared.wait(), 2)
            assert seen[0] is not seen[1]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def test_failed_atomic_write_preserves_previous_cache(tmp_path):
    path = tmp_path / 'meta.json'
    cache.write_json(path, {'title': '原本的歌'})
    with patch.object(Path, 'replace', side_effect=OSError('disk unavailable')):
        with pytest.raises(OSError):
            cache.write_json(path, {'title': '新的歌'})
    assert json.loads(path.read_text(encoding='utf-8')) == {'title': '原本的歌'}
    assert list(tmp_path.iterdir()) == [path]
