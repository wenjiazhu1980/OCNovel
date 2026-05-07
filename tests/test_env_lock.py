# -*- coding: utf-8 -*-
"""ENV_CONFIG_LOCK 并发语义测试

覆盖 src/gui/workers/_env_lock.py 提供的进程级锁：
1. 类型正确（RLock，可重入）
2. 嵌套 acquire 不死锁
3. 并发下临界区互斥（最大并发 = 1）
4. 临界区内 os.environ 不被其它线程穿插污染
"""
import os
import random
import threading
import time

from src.gui.workers._env_lock import ENV_CONFIG_LOCK


def test_env_config_lock_is_rlock():
    """ENV_CONFIG_LOCK 必须是可重入锁（RLock）"""
    rlock_type = type(threading.RLock())
    assert isinstance(ENV_CONFIG_LOCK, rlock_type)


def test_env_config_lock_is_reentrant():
    """同一线程嵌套 acquire 不应死锁"""
    with ENV_CONFIG_LOCK:
        with ENV_CONFIG_LOCK:
            with ENV_CONFIG_LOCK:
                pass


def test_env_config_lock_mutual_exclusion_under_concurrency():
    """10 线程并发进入临界区：最大并发 = 1，os.environ 不被污染"""
    NUM_WORKERS = 10
    in_section = 0
    in_section_lock = threading.Lock()
    max_concurrent = 0
    errors: list[tuple[int, str | None, str]] = []
    created_keys: list[str] = []

    def worker(idx: int):
        nonlocal in_section, max_concurrent
        my_key = f"TEST_ENV_LOCK_W{idx}"
        my_val = f"VAL_{idx}_{random.randint(0, 10000)}"
        created_keys.append(my_key)
        with ENV_CONFIG_LOCK:
            with in_section_lock:
                in_section += 1
                if in_section > max_concurrent:
                    max_concurrent = in_section
            os.environ[my_key] = my_val
            time.sleep(random.uniform(0.005, 0.02))
            got = os.environ.get(my_key)
            if got != my_val:
                errors.append((idx, got, my_val))
            with in_section_lock:
                in_section -= 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(NUM_WORKERS)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_concurrent == 1, (
            f"临界区最大并发 = {max_concurrent}（期望 1），锁互斥失效"
        )
        assert not errors, f"os.environ 被穿插污染: {errors}"
    finally:
        for k in created_keys:
            os.environ.pop(k, None)
