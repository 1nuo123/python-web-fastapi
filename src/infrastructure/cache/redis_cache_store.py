"""
Redis缓存存储基础设施模块。
"""

from __future__ import annotations

import inspect
from http import HTTPStatus

from redis import Redis
from redis.exceptions import RedisError

from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException

REDIS_CACHE_UNAVAILABLE_MESSAGE = "Redis 缓存不可用。"
REDIS_TEXT_ENCODING = "utf-8"
DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS = 2
DEFAULT_REDIS_MAX_CONNECTIONS = 32
INCREMENT_WITH_EXPIRE_SCRIPT = """
local current_value = redis.call('INCR', KEYS[1])
if current_value == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current_value
"""
DELETE_IF_EQUALS_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
REFRESH_IF_EQUALS_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    if ARGV[2] == '' then
        return redis.call('PERSIST', KEYS[1])
    end
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
COMPARE_AND_SET_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    if ARGV[3] == '' then
        redis.call('SET', KEYS[1], ARGV[2])
        return 1
    end
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    return 1
end
return 0
"""


class RedisCacheStore(CacheStore):
    """
    Redis缓存存储实现，负责保存和读取状态。
    """

    def __init__(
        self,
        redis_url: str,
        socket_connect_timeout_seconds: int = DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS,
        max_connections: int = DEFAULT_REDIS_MAX_CONNECTIONS,
    ) -> None:
        """
        初始化Redis缓存存储。

        :param redis_url: Redis 连接地址。约束：需符合 ``str`` 注解。
        :type redis_url: str
        :param socket_connect_timeout_seconds: Redis 连接超时秒数。默认值：`DEFAULT_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS`。约束：需符合 ``int`` 注解。
        :type socket_connect_timeout_seconds: int
        :returns: 无返回值。
        :rtype: None
        """

        self._redis_url = redis_url
        self._socket_connect_timeout_seconds = socket_connect_timeout_seconds
        self._max_connections = max_connections
        self._client: Redis | None = None

    def get_value(self, key: str) -> str | None:
        """
        获取值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: str | None
        """

        value = self._execute_read(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode(REDIS_TEXT_ENCODING)
        return value

    def set_value(self, key: str, value: str, ttl_seconds: int | None) -> None:
        """
        设置值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param value: 当前流程要写入或比较的值。约束：需符合 ``str`` 注解。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数；传入 ``None`` 时表示不过期。
        :type ttl_seconds: int | None
        :returns: 无返回值。
        :rtype: None
        """

        self._execute_write(key=key, value=value, ttl_seconds=ttl_seconds)

    def set_value_if_absent(self, key: str, value: str, ttl_seconds: int | None) -> bool:
        """
        当 Redis 键不存在时原子写入值。

        :param key: 缓存键。
        :type key: str
        :param value: 待写入的原始字符串值。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int | None
        :returns: 写入成功返回 ``True``。
        :rtype: bool
        """

        try:
            return bool(
                self._get_client().set(
                    name=key,
                    value=value,
                    ex=ttl_seconds,
                    nx=True,
                )
            )
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc

    def delete_value_if_equals(self, key: str, expected_value: str) -> bool:
        """
        当 Redis 值匹配时原子删除键。

        :param key: 缓存键。
        :type key: str
        :param expected_value: 预期值。
        :type expected_value: str
        :returns: 删除成功返回 ``True``。
        :rtype: bool
        """

        try:
            result = self._get_client().eval(
                DELETE_IF_EQUALS_SCRIPT,
                1,
                key,
                expected_value,
            )
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc
        return self._read_integer_result(result) > 0

    def refresh_value_if_equals(
        self,
        key: str,
        expected_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当 Redis 值匹配时原子刷新 TTL。

        :param key: 缓存键。
        :type key: str
        :param expected_value: 预期值。
        :type expected_value: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int | None
        :returns: 刷新成功返回 ``True``。
        :rtype: bool
        """

        try:
            result = self._get_client().eval(
                REFRESH_IF_EQUALS_SCRIPT,
                1,
                key,
                expected_value,
                "" if ttl_seconds is None else ttl_seconds,
            )
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc
        return self._read_integer_result(result) > 0

    def compare_and_set_value(
        self,
        key: str,
        expected_value: str,
        next_value: str,
        ttl_seconds: int | None,
    ) -> bool:
        """
        当 Redis 值匹配时原子替换为新值。

        :param key: 缓存键。
        :type key: str
        :param expected_value: 预期值。
        :type expected_value: str
        :param next_value: 新值。
        :type next_value: str
        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int | None
        :returns: 替换成功返回 ``True``。
        :rtype: bool
        """

        try:
            result = self._get_client().eval(
                COMPARE_AND_SET_SCRIPT,
                1,
                key,
                expected_value,
                next_value,
                "" if ttl_seconds is None else ttl_seconds,
            )
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc
        return self._read_integer_result(result) > 0

    def increment_with_expire(self, key: str, ttl_seconds: int) -> int:
        """
        原子递增 Redis 计数并确保首次写入时设置固定窗口过期时间。

        Lua 脚本仅在计数值为首次写入值时设置 TTL；窗口内后续递增不刷新 TTL。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param ttl_seconds: 缓存 TTL 秒数。约束：需符合 ``int`` 注解。
        :type ttl_seconds: int | None
        :returns: 递增后的计数值。
        :rtype: int
        :raises _build_cache_exception: 当 Redis 执行失败时抛出统一缓存异常。
        """

        try:
            result = self._get_client().eval(
                INCREMENT_WITH_EXPIRE_SCRIPT,
                1,
                key,
                ttl_seconds,
            )
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc
        return self._read_integer_result(result)

    def delete_value(self, key: str) -> None:
        """
        删除值。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 无返回值。
        :rtype: None
        :raises _build_cache_exception: 当当前步骤检测到异常条件时抛出。
        """

        try:
            self._get_client().delete(key)
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc

    def close(self) -> None:
        """
        处理关闭。

        :returns: 无返回值。
        :rtype: None
        """

        if self._client is not None:
            self._client.close()
            self._client = None

    def assert_available(self) -> None:
        """
        断言可用。

        :returns: 无返回值。
        :rtype: None
        :raises _build_cache_exception: 当当前步骤检测到异常条件时抛出。
        """

        try:
            self._get_client().ping()
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc

    def _get_client(self) -> Redis:
        """
        获取客户端。

        :returns: 返回当前操作结果。
        :rtype: Redis
        """

        if self._client is None:
            self._client = Redis.from_url(
                self._redis_url,
                decode_responses=True,
                encoding=REDIS_TEXT_ENCODING,
                socket_connect_timeout=self._socket_connect_timeout_seconds,
                max_connections=self._max_connections,
            )
        return self._client

    def _execute_read(self, key: str) -> str | bytes | None:
        """
        处理执行读取。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 返回当前操作结果。
        :rtype: str | bytes | None
        :raises _build_cache_exception: 当当前步骤检测到异常条件时抛出。
        """

        try:
            result = self._get_client().get(key)
            if inspect.isawaitable(result):
                raise TypeError("同步 Redis 客户端返回了异步读取结果。")
            if result is None or isinstance(result, str | bytes):
                return result
            raise TypeError("Redis 读取结果类型不正确。")
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc

    def _execute_write(self, *, key: str, value: str, ttl_seconds: int | None) -> None:
        """
        处理执行写入。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param value: 当前流程要写入或比较的值。约束：需符合 ``str`` 注解。
        :type value: str
        :param ttl_seconds: 缓存 TTL 秒数；传入 ``None`` 时表示不过期。
        :type ttl_seconds: int | None
        :returns: 无返回值。
        :rtype: None
        :raises _build_cache_exception: 当当前步骤检测到异常条件时抛出。
        """

        try:
            self._get_client().set(name=key, value=value, ex=ttl_seconds)
        except RedisError as exc:
            raise self._build_cache_exception(exc) from exc

    def _build_cache_exception(self, exc: Exception) -> HttpFaultException:
        """
        构建缓存异常。

        :param exc: 当前捕获到的异常对象。约束：需符合 ``Exception`` 注解。
        :type exc: Exception
        :returns: 返回当前操作结果。
        :rtype: HttpFaultException
        """

        return HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.CACHE_UNAVAILABLE,
            message=REDIS_CACHE_UNAVAILABLE_MESSAGE,
            detail=str(exc),
        )

    def _read_integer_result(self, result: object) -> int:
        """读取 Redis 整数结果。

        :param result: Redis 命令结果。
        :type result: object
        :returns: 整数结果。
        :rtype: int
        :raises TypeError: 当同步客户端返回异步或非整数结果时抛出。
        """

        if inspect.isawaitable(result):
            raise TypeError("同步 Redis 客户端返回了异步命令结果。")
        if isinstance(result, int | str | bytes):
            return int(result)
        raise TypeError("Redis 命令结果不是整数。")
