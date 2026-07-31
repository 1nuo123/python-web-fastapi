"""应用配置加载器基础设施模块。"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, cast

import rtoml
from pydantic import (
    ValidationError,
)

from src.core.cache_contract.cache_runtime_contract import CacheBackend
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.logging_contract.log_runtime_contract import (
    LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
    LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
)
from src.core.task_contract.task_runtime_contract import (
    MessageBackend,
)
from src.infrastructure.settings.dotenv_settings_loader import DotenvSettingsLoader
from src.infrastructure.settings.parsers.module_settings_parser import (
    ModuleSettingsParser,
)
from src.infrastructure.settings.parsers.runtime_settings_parser import (
    RuntimeSettingsParser,
)
from src.infrastructure.settings.settings_mapping_merger import (
    SettingsMappingInput,
    SettingsMappingMerger,
)

if TYPE_CHECKING:
    from src.infrastructure.settings.settings_security_validator import (
        SettingsSecurityValidator,
    )

from src.infrastructure.settings.application_settings import (
    API_PREFIX_FIELD_KEY,
    APP_ENVIRONMENT_VARIABLE,
    APP_SECTION_KEY,
    AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
    AUTH_MODULE_SECTION_KEY,
    AUTH_RUNTIME_SECTION_KEY,
    BACKEND_DETAIL_FIELD_KEY,
    BACKEND_FIELD_KEY,
    BOOTSTRAP_ADMIN_SECTION_KEY,
    CACHE_RUNTIME_SECTION_KEY,
    DATABASE_RUNTIME_SECTION_KEY,
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    DISTRIBUTED_LOCK_RUNTIME_DIRECTORY_NAME,
    DISTRIBUTED_LOCK_RUNTIME_SECTION_KEY,
    ENTRY_LOG_PATH_FIELD_KEY,
    ENTRY_PROJECT_NAME_FIELD_KEY,
    JWT_SECRET_ENVIRONMENT_VARIABLE,
    KEY_MANAGEMENT_RUNTIME_DIRECTORY_NAME,
    KEY_MANAGEMENT_RUNTIME_SECTION_KEY,
    LOGGING_RUNTIME_DIRECTORY_NAME,
    LOGGING_RUNTIME_SECTION_KEY,
    MESSAGE_RUNTIME_SECTION_KEY,
    METRICS_RUNTIME_DIRECTORY_NAME,
    METRICS_RUNTIME_SECTION_KEY,
    OTEL_RUNTIME_SECTION_KEY,
    PASSWORD_PLAIN_FIELD_KEY,
    RABBITMQ_URL_ENVIRONMENT_VARIABLE,
    RABBITMQ_URL_FIELD_KEY,
    REDIS_URL_ENVIRONMENT_VARIABLE,
    REDIS_URL_FIELD_KEY,
    RUNTIME_SECTION_KEY,
    RUNTIME_WEB_API_PREFIX_ENVIRONMENT_VARIABLE,
    SECURITY_RUNTIME_SECTION_KEY,
    SETTINGS_LOGGER_NAME,
    STREAM_RUNTIME_DIRECTORY_NAME,
    STREAM_RUNTIME_SECTION_KEY,
    SYSTEM_MODULE_SECTION_KEY,
    TASK_MODULE_SECTION_KEY,
    TASK_RUNTIME_SECTION_KEY,
    WEB_RUNTIME_SECTION_KEY,
    AppEnvironment,
    ApplicationSettings,
)
from src.infrastructure.settings.raw_application_settings import (
    RawSettingsMapping,
    RawTomlContent,
    SettingsOverrideMapping,
)


class AppSettingsLoader:
    """
    应用配置加载器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, config_root: str | Path = "config") -> None:
        """
        初始化应用配置加载器。

        :param config_root: 配置根目录路径。默认值：`'config'`。约束：需符合 ``str | Path`` 注解。
        :type config_root: str | Path
        :returns: 无返回值。
        :rtype: None
        """

        self._config_root = Path(config_root)
        self._logger = logging.getLogger(SETTINGS_LOGGER_NAME)
        self._module_settings_parser = ModuleSettingsParser()
        self._runtime_settings_parser = RuntimeSettingsParser()
        self._settings_mapping_merger = SettingsMappingMerger()
        self._dotenv_settings_loader = DotenvSettingsLoader()
        self._dotenv_path = self._config_root.parent / ".env"

    def load(self) -> ApplicationSettings:
        """
        处理加载。

        :returns: 返回当前操作结果。
        :rtype: ApplicationSettings
        """

        environment_name = os.getenv(
            APP_ENVIRONMENT_VARIABLE,
            AppEnvironment.DEVELOPMENT,
        )
        return self.load_for_environment(AppEnvironment(environment_name))

    def load_for_environment(self, environment: AppEnvironment) -> ApplicationSettings:
        """
        加载用于环境。

        :param environment: 目标运行环境，用于选择配置文件层级。约束：需符合 ``AppEnvironment`` 注解。
        :type environment: AppEnvironment
        :returns: 返回当前操作结果。
        :rtype: ApplicationSettings
        """

        raw_settings = self._build_raw_settings(environment)
        raw_settings = self._apply_dotenv_overrides(
            raw_settings,
            environment=environment,
        )
        raw_settings = self._apply_environment_overrides(
            raw_settings,
            environment=environment,
        )
        return self._validate_settings(raw_settings)

    def load_from_mapping(
        self,
        *,
        environment: AppEnvironment,
        overrides: SettingsOverrideMapping,
    ) -> ApplicationSettings:
        """
        加载从映射。

        :param environment: 目标运行环境，用于选择配置文件层级。约束：需符合 ``AppEnvironment`` 注解。
        :type environment: AppEnvironment
        :param overrides: 覆盖配置映射，会在文件配置基础上递归合并。约束：需符合 ``SettingsOverrideMapping`` 注解。
        :type overrides: SettingsOverrideMapping
        :returns: 返回当前操作结果。
        :rtype: ApplicationSettings
        """

        raw_settings = self._build_raw_settings(environment)
        raw_settings = self._apply_dotenv_overrides(
            raw_settings,
            environment=environment,
        )
        merged_settings = self._merge_mapping(raw_settings, overrides)
        merged_settings = self._apply_environment_overrides(
            merged_settings,
            environment=environment,
        )
        return self._validate_settings(merged_settings)

    def _build_raw_settings(self, environment: AppEnvironment) -> RawSettingsMapping:
        """
        构建原始配置。

        :param environment: 目标运行环境，用于选择配置文件层级。约束：需符合 ``AppEnvironment`` 注解。
        :type environment: AppEnvironment
        :returns: 返回当前操作结果。
        :rtype: RawSettingsMapping
        """

        merged_settings: RawSettingsMapping = {
            APP_SECTION_KEY: {},
            SYSTEM_MODULE_SECTION_KEY: {},
            AUTH_MODULE_SECTION_KEY: {},
            TASK_MODULE_SECTION_KEY: {},
            RUNTIME_SECTION_KEY: {
                WEB_RUNTIME_SECTION_KEY: {},
                SECURITY_RUNTIME_SECTION_KEY: {},
                DISTRIBUTED_LOCK_RUNTIME_SECTION_KEY: {},
                KEY_MANAGEMENT_RUNTIME_SECTION_KEY: {},
                AUTH_RUNTIME_SECTION_KEY: {},
                DATABASE_RUNTIME_SECTION_KEY: {},
                CACHE_RUNTIME_SECTION_KEY: {},
                MESSAGE_RUNTIME_SECTION_KEY: {},
                TASK_RUNTIME_SECTION_KEY: {},
                OTEL_RUNTIME_SECTION_KEY: {},
                METRICS_RUNTIME_SECTION_KEY: {},
                LOGGING_RUNTIME_SECTION_KEY: {},
                STREAM_RUNTIME_SECTION_KEY: {},
            },
        }
        # 文件按“基础层 -> 环境层”的顺序依次覆盖，后读到的配置拥有更高优先级。
        for file_path in self._collect_file_paths(environment):
            if not file_path.exists():
                continue
            file_content = self._read_toml(file_path)
            merged_settings = self._merge_mapping(
                merged_settings,
                self._parse_routed_file_content(file_path, file_content),
            )
        return merged_settings

    def _collect_file_paths(self, environment: AppEnvironment) -> list[Path]:
        """
        收集文件路径集合。

        :param environment: 目标运行环境，用于选择配置文件层级。约束：需符合 ``AppEnvironment`` 注解。
        :type environment: AppEnvironment
        :returns: 返回按实现构造的列表结果。
        :rtype: list[Path]
        """

        environment_name = environment.value
        return [
            self._config_root / "app_base.toml",
            self._config_root / f"app_{environment_name}.toml",
            self._config_root / "modules" / "system_module" / "system_module_base.toml",
            self._config_root
            / "modules"
            / "system_module"
            / f"system_module_{environment_name}.toml",
            self._config_root / "modules" / "auth_module" / "auth_module_base.toml",
            self._config_root / "modules" / "auth_module" / f"auth_module_{environment_name}.toml",
            self._config_root / "modules" / "task_module" / "task_module_base.toml",
            self._config_root / "modules" / "task_module" / f"task_module_{environment_name}.toml",
            self._config_root / "runtime" / "web_runtime" / "web_runtime_base.toml",
            self._config_root / "runtime" / "web_runtime" / f"web_runtime_{environment_name}.toml",
            self._config_root / "runtime" / "security_runtime" / "security_runtime_base.toml",
            self._config_root
            / "runtime"
            / "security_runtime"
            / f"security_runtime_{environment_name}.toml",
            self._config_root
            / "runtime"
            / DISTRIBUTED_LOCK_RUNTIME_DIRECTORY_NAME
            / "distributed_lock_runtime_base.toml",
            self._config_root
            / "runtime"
            / DISTRIBUTED_LOCK_RUNTIME_DIRECTORY_NAME
            / f"distributed_lock_runtime_{environment_name}.toml",
            self._config_root
            / "runtime"
            / KEY_MANAGEMENT_RUNTIME_DIRECTORY_NAME
            / "key_management_runtime_base.toml",
            self._config_root
            / "runtime"
            / KEY_MANAGEMENT_RUNTIME_DIRECTORY_NAME
            / f"key_management_runtime_{environment_name}.toml",
            self._config_root / "runtime" / "auth_runtime" / "auth_runtime_base.toml",
            self._config_root
            / "runtime"
            / "auth_runtime"
            / f"auth_runtime_{environment_name}.toml",
            self._config_root / "runtime" / "database_runtime" / "database_runtime_base.toml",
            self._config_root
            / "runtime"
            / "database_runtime"
            / f"database_runtime_{environment_name}.toml",
            self._config_root / "runtime" / "cache_runtime" / "cache_runtime_base.toml",
            self._config_root
            / "runtime"
            / "cache_runtime"
            / f"cache_runtime_{environment_name}.toml",
            self._config_root / "runtime" / "message_runtime" / "message_runtime_base.toml",
            self._config_root
            / "runtime"
            / "message_runtime"
            / f"message_runtime_{environment_name}.toml",
            self._config_root / "runtime" / "task_runtime" / "task_runtime_base.toml",
            self._config_root
            / "runtime"
            / "task_runtime"
            / f"task_runtime_{environment_name}.toml",
            self._config_root / "runtime" / "otel_runtime" / "otel_runtime_base.toml",
            self._config_root
            / "runtime"
            / "otel_runtime"
            / f"otel_runtime_{environment_name}.toml",
            self._config_root
            / "runtime"
            / METRICS_RUNTIME_DIRECTORY_NAME
            / "metrics_runtime_base.toml",
            self._config_root
            / "runtime"
            / METRICS_RUNTIME_DIRECTORY_NAME
            / f"metrics_runtime_{environment_name}.toml",
            self._config_root
            / "runtime"
            / LOGGING_RUNTIME_DIRECTORY_NAME
            / "logging_runtime_base.toml",
            self._config_root
            / "runtime"
            / LOGGING_RUNTIME_DIRECTORY_NAME
            / f"logging_runtime_{environment_name}.toml",
            self._config_root
            / "runtime"
            / STREAM_RUNTIME_DIRECTORY_NAME
            / "stream_runtime_base.toml",
            self._config_root
            / "runtime"
            / STREAM_RUNTIME_DIRECTORY_NAME
            / f"stream_runtime_{environment_name}.toml",
        ]

    def _read_toml(self, file_path: Path) -> RawTomlContent:
        """
        读取TOML。

        :param file_path: 当前读取或路由的文件路径。约束：需符合 ``Path`` 注解。
        :type file_path: Path
        :returns: 返回当前操作结果。
        :rtype: RawTomlContent
        """

        with file_path.open("r", encoding="utf-8") as file:
            return cast(RawTomlContent, rtoml.load(file))

    def _apply_dotenv_overrides(
        self,
        raw_settings: RawSettingsMapping,
        *,
        environment: AppEnvironment,
    ) -> RawSettingsMapping:
        """
        应用本地 dotenv 覆盖配置。

        :param raw_settings: 尚未完成模型校验的原始配置树。
        :type raw_settings: RawSettingsMapping
        :param environment: 目标运行环境。
        :type environment: AppEnvironment
        :returns: 合并 dotenv 后的原始配置树。
        :rtype: RawSettingsMapping
        """

        dotenv_enabled = environment != AppEnvironment.PRODUCTION
        self._dotenv_settings_loader.build_local_startup_policy(
            environment=environment.value,
            dotenv_enabled=dotenv_enabled,
        )
        dotenv_result = self._dotenv_settings_loader.load(
            dotenv_path=self._dotenv_path,
            environment=environment.value,
            enabled=dotenv_enabled,
        )
        return self._apply_source_overrides(
            raw_settings,
            source_values=dotenv_result.variables,
        )

    def _apply_environment_overrides(
        self,
        raw_settings: RawSettingsMapping,
        *,
        environment: AppEnvironment,
    ) -> RawSettingsMapping:
        """
        应用环境覆盖配置。

        :param raw_settings: 尚未完成模型校验的原始配置树。约束：需符合 ``RawSettingsMapping`` 注解。
        :type raw_settings: RawSettingsMapping
        :param environment: 目标运行环境。
        :type environment: AppEnvironment
        :returns: 返回当前操作结果。
        :rtype: RawSettingsMapping
        :raises ValueError: 生产密钥缺失或使用弱密钥时抛出。
        """

        self._dotenv_settings_loader.build_process_source_envelope(environment=environment.value)
        process_values = {
            DATABASE_URL_ENVIRONMENT_VARIABLE: os.getenv(DATABASE_URL_ENVIRONMENT_VARIABLE),
            REDIS_URL_ENVIRONMENT_VARIABLE: os.getenv(REDIS_URL_ENVIRONMENT_VARIABLE),
            RABBITMQ_URL_ENVIRONMENT_VARIABLE: os.getenv(RABBITMQ_URL_ENVIRONMENT_VARIABLE),
            JWT_SECRET_ENVIRONMENT_VARIABLE: os.getenv(JWT_SECRET_ENVIRONMENT_VARIABLE),
            AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE: os.getenv(
                AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE
            ),
            RUNTIME_WEB_API_PREFIX_ENVIRONMENT_VARIABLE: os.getenv(
                RUNTIME_WEB_API_PREFIX_ENVIRONMENT_VARIABLE
            ),
            LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE: os.getenv(
                LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE
            ),
            LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE: os.getenv(
                LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE
            ),
        }
        if environment == AppEnvironment.PRODUCTION:
            self._build_security_validator().validate_production_environment(
                jwt_secret=process_values[JWT_SECRET_ENVIRONMENT_VARIABLE],
                database_url=process_values[DATABASE_URL_ENVIRONMENT_VARIABLE],
                redis_url=process_values[REDIS_URL_ENVIRONMENT_VARIABLE],
                rabbitmq_url=process_values[RABBITMQ_URL_ENVIRONMENT_VARIABLE],
            )
        # 环境变量始终最后覆盖，用于容器部署时替换敏感信息和连接地址。
        return self._apply_source_overrides(raw_settings, source_values=process_values)

    def _apply_source_overrides(
        self,
        raw_settings: RawSettingsMapping,
        *,
        source_values: Mapping[str, str | None],
    ) -> RawSettingsMapping:
        """
        应用环境变量来源覆盖。

        :param raw_settings: 尚未完成模型校验的原始配置树。
        :type raw_settings: RawSettingsMapping
        :param source_values: 来源变量映射。
        :type source_values: dict[str, str | None]
        :returns: 应用覆盖后的原始配置树。
        :rtype: RawSettingsMapping
        """

        override_tree: SettingsOverrideMapping = {}
        database_url = source_values.get(DATABASE_URL_ENVIRONMENT_VARIABLE)
        redis_url = source_values.get(REDIS_URL_ENVIRONMENT_VARIABLE)
        rabbitmq_url = source_values.get(RABBITMQ_URL_ENVIRONMENT_VARIABLE)
        jwt_secret = source_values.get(JWT_SECRET_ENVIRONMENT_VARIABLE)
        bootstrap_admin_password = source_values.get(
            AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE
        )
        runtime_web_api_prefix = source_values.get(RUNTIME_WEB_API_PREFIX_ENVIRONMENT_VARIABLE)
        logging_entry_project_name = source_values.get(
            LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE
        )
        logging_entry_log_path = source_values.get(LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE)
        if runtime_web_api_prefix is not None:
            override_tree = self._merge_mapping(
                override_tree,
                {
                    RUNTIME_SECTION_KEY: {
                        WEB_RUNTIME_SECTION_KEY: {API_PREFIX_FIELD_KEY: runtime_web_api_prefix}
                    }
                },
            )
        if database_url is not None:
            override_tree = self._merge_mapping(
                override_tree,
                {RUNTIME_SECTION_KEY: {DATABASE_RUNTIME_SECTION_KEY: {"url": database_url}}},
            )
        if redis_url is not None and self._should_apply_cache_url_override(
            raw_settings,
        ):
            override_tree = self._merge_mapping(
                override_tree,
                {
                    RUNTIME_SECTION_KEY: {
                        CACHE_RUNTIME_SECTION_KEY: {
                            BACKEND_DETAIL_FIELD_KEY: {REDIS_URL_FIELD_KEY: redis_url}
                        }
                    }
                },
            )
        if redis_url is not None and self._should_apply_stream_url_override(raw_settings):
            override_tree = self._merge_mapping(
                override_tree,
                {
                    RUNTIME_SECTION_KEY: {
                        STREAM_RUNTIME_SECTION_KEY: {"detail": {REDIS_URL_FIELD_KEY: redis_url}}
                    }
                },
            )
        if rabbitmq_url is not None and self._should_apply_message_url_override(
            raw_settings,
        ):
            override_tree = self._merge_mapping(
                override_tree,
                {
                    RUNTIME_SECTION_KEY: {
                        MESSAGE_RUNTIME_SECTION_KEY: {
                            BACKEND_DETAIL_FIELD_KEY: {RABBITMQ_URL_FIELD_KEY: rabbitmq_url}
                        }
                    }
                },
            )
        if jwt_secret is not None:
            override_tree = self._merge_mapping(
                override_tree,
                {RUNTIME_SECTION_KEY: {AUTH_RUNTIME_SECTION_KEY: {"jwt_secret": jwt_secret}}},
            )
        if bootstrap_admin_password is not None:
            override_tree = self._merge_mapping(
                override_tree,
                {
                    AUTH_MODULE_SECTION_KEY: {
                        BOOTSTRAP_ADMIN_SECTION_KEY: {
                            PASSWORD_PLAIN_FIELD_KEY: bootstrap_admin_password
                        }
                    }
                },
            )
        if logging_entry_project_name is not None:
            override_tree = self._merge_mapping(
                override_tree,
                {
                    RUNTIME_SECTION_KEY: {
                        LOGGING_RUNTIME_SECTION_KEY: {
                            ENTRY_PROJECT_NAME_FIELD_KEY: logging_entry_project_name
                        }
                    }
                },
            )
        if logging_entry_log_path is not None:
            override_tree = self._merge_mapping(
                override_tree,
                {
                    RUNTIME_SECTION_KEY: {
                        LOGGING_RUNTIME_SECTION_KEY: {
                            ENTRY_LOG_PATH_FIELD_KEY: logging_entry_log_path
                        }
                    }
                },
            )
        return self._merge_mapping(raw_settings, override_tree)

    def _should_apply_cache_url_override(
        self,
        raw_settings: RawSettingsMapping,
    ) -> bool:
        """
        判断是否应把 Redis 连接串覆盖到缓存明细。

        :param raw_settings: 已合并文件与显式覆盖后的原始配置。
        :type raw_settings: RawSettingsMapping
        :returns: 当缓存后端为 Redis 时返回 ``True``。
        :rtype: bool
        """

        cache_settings = raw_settings.get(RUNTIME_SECTION_KEY, {}).get(
            CACHE_RUNTIME_SECTION_KEY,
            {},
        )
        return cache_settings.get(BACKEND_FIELD_KEY) == CacheBackend.REDIS.value

    def _should_apply_message_url_override(
        self,
        raw_settings: RawSettingsMapping,
    ) -> bool:
        """
        判断是否应把 RabbitMQ 连接串覆盖到消息明细。

        :param raw_settings: 已合并文件与显式覆盖后的原始配置。
        :type raw_settings: RawSettingsMapping
        :returns: 当消息后端为 RabbitMQ 时返回 ``True``。
        :rtype: bool
        """

        message_settings = raw_settings.get(RUNTIME_SECTION_KEY, {}).get(
            MESSAGE_RUNTIME_SECTION_KEY,
            {},
        )
        return message_settings.get(BACKEND_FIELD_KEY) == MessageBackend.RABBITMQ.value

    def _should_apply_stream_url_override(self, raw_settings: RawSettingsMapping) -> bool:
        """判断是否应把 Redis 连接串覆盖到流运行时。

        :param raw_settings: 已合并文件配置。
        :type raw_settings: RawSettingsMapping
        :returns: 流运行时使用 Redis 时返回 ``True``。
        :rtype: bool
        """

        stream_settings = raw_settings.get(RUNTIME_SECTION_KEY, {}).get(
            STREAM_RUNTIME_SECTION_KEY,
            {},
        )
        header = stream_settings.get("header", {})
        return header.get("mode") == "redis_stream_runtime"

    def _validate_settings(self, raw_settings: RawSettingsMapping) -> ApplicationSettings:
        """
        校验配置。

        :param raw_settings: 尚未完成模型校验的原始配置树。约束：需符合 ``RawSettingsMapping`` 注解。
        :type raw_settings: RawSettingsMapping
        :returns: 返回当前操作结果。
        :rtype: ApplicationSettings
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        try:
            settings = ApplicationSettings.model_validate(
                {
                    APP_SECTION_KEY: raw_settings.get(APP_SECTION_KEY, {}),
                    "modules": {
                        "system": raw_settings.get(SYSTEM_MODULE_SECTION_KEY, {}),
                        "auth": raw_settings.get(AUTH_MODULE_SECTION_KEY, {}),
                        "task": raw_settings.get(TASK_MODULE_SECTION_KEY, {}),
                    },
                    RUNTIME_SECTION_KEY: raw_settings.get(RUNTIME_SECTION_KEY, {}),
                }
            )
            self._build_security_validator().validate_settings(settings)
            return settings
        except (ValidationError, ValueError) as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message="配置校验失败。",
                detail=str(exc),
            ) from exc

    def _parse_routed_file_content(
        self,
        file_path: Path,
        file_content: RawTomlContent,
    ) -> RawSettingsMapping:
        """
        使用分节解析器路由配置文件内容。
        """

        module_section = self._module_settings_parser.parse_section(
            file_path=file_path,
            file_content=cast(dict[str, object], file_content),
        )
        if module_section is not None:
            return cast(
                RawSettingsMapping,
                self._module_settings_parser.extract_mapping(module_section),
            )
        runtime_section = self._runtime_settings_parser.parse_section(
            file_path=file_path,
            file_content=cast(dict[str, object], file_content),
        )
        if runtime_section is not None:
            return cast(
                RawSettingsMapping,
                self._runtime_settings_parser.extract_mapping(runtime_section),
            )
        return RawSettingsMapping()

    def _merge_mapping(
        self,
        base_value: RawSettingsMapping,
        override_value: SettingsOverrideMapping,
    ) -> RawSettingsMapping:
        """
        合并映射。

        :param base_value: 递归合并时的基准映射。约束：需符合 ``RawSettingsMapping`` 注解。
        :type base_value: RawSettingsMapping
        :param override_value: 递归合并时的覆盖映射。约束：需符合 ``SettingsOverrideMapping`` 注解。
        :type override_value: SettingsOverrideMapping
        :returns: 返回递归合并后的配置映射。
        :rtype: RawSettingsMapping
        """

        return cast(
            RawSettingsMapping,
            self._settings_mapping_merger.merge(
                cast(SettingsMappingInput, base_value),
                cast(SettingsMappingInput, override_value),
            ),
        )

    def _build_security_validator(self) -> SettingsSecurityValidator:
        """
        构建配置安全校验器。
        """

        from src.infrastructure.settings.settings_security_validator import (
            SettingsSecurityValidator,
        )

        return SettingsSecurityValidator()
