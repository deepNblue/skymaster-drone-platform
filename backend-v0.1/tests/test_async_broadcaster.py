"""AsyncBroadcaster unit tests."""
import asyncio

import pytest

from app.services.async_broadcaster import AsyncBroadcaster, get_broadcaster, reset_broadcaster


@pytest.fixture
def br():
    return AsyncBroadcaster(queue_size=8)


async def test_single_subscriber_receives_event(br):
    async def sub():
        events = []
        async for ev in br.subscribe("scene-1", heartbeat_interval=0.1):
            events.append(ev)
            if len(events) >= 2:
                return events

    task = asyncio.create_task(sub())
    await asyncio.sleep(0.05)  # let subscribe register
    await br.publish("scene-1", {"status": "training", "seq": 1})
    await br.publish("scene-1", {"status": "training", "seq": 2})
    events = await asyncio.wait_for(task, timeout=2.0)
    assert len(events) == 2
    assert events[0]["seq"] == 1
    assert events[1]["seq"] == 2


async def test_fanout_multi_subscribers(br):
    """3 个订阅者都应收到同一个事件."""
    results = []

    async def sub(sid):
        got = []
        async for ev in br.subscribe("scene-x", heartbeat_interval=0.1):
            got.append(ev)
            break
        results.append((sid, got))

    tasks = [asyncio.create_task(sub(i)) for i in range(3)]
    await asyncio.sleep(0.05)
    delivered = await br.publish("scene-x", {"status": "ready"})
    await asyncio.gather(*tasks)

    assert delivered == 3
    assert len(results) == 3
    for sid, got in results:
        assert got == [{"status": "ready"}]


async def test_topic_isolation(br):
    """topic A 的事件不应打到 topic B 的订阅者."""
    got_a, got_b = [], []

    async def sub(topic, into):
        async for ev in br.subscribe(topic, heartbeat_interval=0.1):
            into.append(ev)
            return

    ta = asyncio.create_task(sub("A", got_a))
    tb = asyncio.create_task(sub("B", got_b))
    await asyncio.sleep(0.05)

    await br.publish("A", {"topic": "A"})
    await ta
    # B 应超时后被下面的 publish 唤醒
    await br.publish("B", {"topic": "B"})
    await tb

    assert got_a == [{"topic": "A"}]
    assert got_b == [{"topic": "B"}]


async def test_initial_snapshot(br):
    """subscribe 时传 initial 应立即 yield."""
    async def sub():
        async for ev in br.subscribe("s", initial={"init": True}, heartbeat_interval=0.1):
            return ev

    task = asyncio.create_task(sub())
    got = await asyncio.wait_for(task, timeout=1.0)
    assert got == {"init": True}


async def test_heartbeat_yields_none(br):
    """静默期应 yield None 作为 keepalive 信号."""
    async def sub():
        async for ev in br.subscribe("s", heartbeat_interval=0.05):
            return ev

    task = asyncio.create_task(sub())
    got = await asyncio.wait_for(task, timeout=1.0)
    assert got is None


async def test_slow_consumer_drops_events(br):
    """满队列时 publish 不阻塞, drop 计数增加."""
    # 订阅但不消费
    q_saw_first = asyncio.Event()

    async def slow_sub():
        i = 0
        async for ev in br.subscribe("slow", heartbeat_interval=1.0):
            if i == 0:
                q_saw_first.set()
                await asyncio.sleep(2.0)  # 卡住
            i += 1

    task = asyncio.create_task(slow_sub())
    # 等 subscribe 注册好
    await asyncio.sleep(0.05)

    # 灌 queue_size + 5 个事件
    for i in range(br._queue_size + 5):
        await br.publish("slow", {"seq": i})

    stats = br.stats()
    assert stats["dropped_total"] >= 5
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_subscriber_cleanup_on_exit(br):
    """订阅者退出后应从内部 dict 清除."""
    # 直接操作 async generator, 显式 aclose
    gen = br.subscribe("cleanup", initial={"init": True}, heartbeat_interval=5.0)
    first = await gen.__anext__()
    assert first == {"init": True}
    assert br.topic_count("cleanup") == 1

    # 关闭 generator, finally 应立即执行
    await gen.aclose()
    assert br.topic_count("cleanup") == 0


def test_singleton():
    reset_broadcaster()
    a = get_broadcaster()
    b = get_broadcaster()
    assert a is b
    reset_broadcaster()
    c = get_broadcaster()
    assert c is not a
