"""全局互斥锁，用于保护 worker 启动时 os.environ + Config 的读写阶段。

背景：Config.__init__ 会调用 load_dotenv(..., override=True) 改写 os.environ，
而 AIConfig 会立刻读 os.getenv()。多个 worker 并发启动时，两个 load_dotenv
可能互相覆盖、读到对方的临时值。此锁串行化这段"读 env + 构造 Config"阶段，
一旦 Config 构造完成，之后的长跑阶段不再访问 os.environ，可以完全并发。
"""
import threading

# 进程级单例
ENV_CONFIG_LOCK = threading.RLock()
