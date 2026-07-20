# 鉴权体系审查报告
**总体定位**

这套鉴权体系本质上不是“只靠 JWT 自证”的轻量方案，而是“JWT 负责携带会话标识，数据库负责提供授权真值，refresh token session 负责控制会话生命周期”的分层鉴权体系。它的核心目标有四个：

1. 给客户端签发 access token 和 refresh token。
2. 在受保护请求上识别当前调用者是谁。
3. 不直接信任 token 内嵌的角色和权限，而是回库读取最新授权快照。
4. 通过 refresh token session 的持久化状态，实现刷新、撤销、复用检测和整会话失效。

**一、配置层的功能**

配置层分成两类：模块配置和运行时配置。

`config/modules/auth_module` 负责描述“鉴权模块作为业务能力是否启用，以及它的业务默认状态是什么”。这一层更偏功能开关和初始业务数据，主要包括：

- 是否启用鉴权模块。
- 是否启用 bootstrap admin。
- bootstrap admin 的用户名、密码、显示名、是否激活。
- 初始角色与 scope 绑定关系，也就是启动时要不要自动生成管理员角色、管理员权限以及对应的用户角色绑定。

`config/runtime/auth_runtime` 负责描述“鉴权能力以什么安全参数运行”。这一层更偏安全运行时参数，主要包括：

- JWT secret。
- JWT algorithm、issuer、audience。
- access token 和 refresh token 的有效期。
- refresh token 是否采用轮换策略。
- 登录失败节流阈值。
- refresh 失败节流阈值。

这两层配置最终会被总配置装载器读入，合并基础配置、环境配置、`.env` 和环境变量，组装成统一的 `ApplicationSettings`，然后再交给安全校验器做基线校验。当前实现中，`jwt_secret` 在运行时 settings 内使用 `SecretStr` 承载；生产环境还会强制外部注入 JWT 密钥、使用分布式鉴权节流、禁止内存鉴权节流，并禁止启用 bootstrap admin。也就是说，配置层的职责不是直接参与鉴权判断，而是决定整套鉴权系统“能否启动、以什么参数启动、启动后默认具备什么业务身份数据”。

**二、注册与装配层的功能**

鉴权体系不是独立脚本，而是被注册到整个 FastAPI 应用里的。装配层负责把“配置、路由、中间件、仓储、JWT 服务、密码器、缓存、数据库”连接成一套真实可用的运行系统。

这部分的完整功能包括：

- 从 ASGI 入口启动应用装配。
- 读取 Web 模块清单，确认鉴权路由 provider 已经注册。
- 构建路由 bundle，把 `/auth/token`、`/auth/refresh`、`/auth/revoke`、`/auth/me` 等端点真正挂到 FastAPI。
- 构建中间件链，确保鉴权绑定中间件在正确的位置执行。
- 构建 `SharedResourceMount`，把 JWT 服务、密码哈希器、授权判断器、节流器、数据库会话工厂、仓储实现、日志组件等统一挂载。
- 在应用启动阶段按配置决定是否初始化数据库、缓存、日志和 bootstrap admin。

这里最关键的设计点是：`SharedResourceMount` 是整个鉴权体系的“运行时总线”。上层路由和 usecase 不直接 new 底层对象，而是通过 mount 暴露的 accessor 和 port 来获取能力。这保证了应用层依赖的是抽象能力，不直接依赖具体实现。

**三、API 层的功能**

API 层是整个鉴权体系对外暴露的 HTTP 边界。它承担四类功能：

1. 接收请求并做请求体解析。
2. 调用对应 usecase。
3. 对受保护接口声明路由级鉴权依赖，并在依赖中读取当前 principal。
4. 把 usecase 结果转换成标准响应。

从职责上看，API 层主要包括以下几类端点：

- `/auth/token`：用户名密码登录，签发 token 对。
- `/auth/refresh`：用 refresh token 换取新的 token 对。
- `/auth/revoke`：撤销 refresh token 对应的 token session。
- `/auth/me`：读取当前已认证主体信息。
- 其他受保护接口，例如系统信息类接口，也通过同样的路由级依赖读取 principal 并做授权判断。

这一层不直接做数据库查询、不直接验密码、不直接维护 refresh token 状态。它只负责 HTTP 适配。受保护路由通过 `Depends` / `Security` 声明 Bearer 安全要求与授权依赖，把真正的认证与授权业务交给应用层和 guard。

**四、中间件层的功能**

中间件层是“每个请求进来后，先统一处理一遍”的地方。鉴权体系里最核心的是 `AuthenticationBindingMiddleware`。

它的完整职责是：

- 从请求头中提取 Bearer token。
- 如果没有 token，则通常不主动报错，而是让请求继续往下走。
- 如果有 token，则调用 JWT 服务验证签名和标准字段。
- 从 token 中拿到 subject、token id、session id、token_use 等信息。
- 根据 subject 回库查询当前用户的授权快照，而不是信任 token 内的旧角色和旧 scope。
- 根据 token session id 回库查询当前 refresh session 的状态，判断该 session 是否被撤销、是否仍然有效。
- 如果一切正常，则把“已认证主体 principal”绑定到 `request.state`。
- 如果失败，则把归一化后的鉴权错误绑定到 `request.state`，并对携带无效 Bearer 的请求直接返回鉴权失败响应。

这层的设计含义非常重要：它负责“识别请求携带的身份”，并且会主动拒绝无效 Bearer，避免公共路由携带坏 token 时仍然返回成功。对于没有携带 token 的请求，它仍然只绑定空认证上下文，是否要求登录和授权由路由级依赖决定。

除了鉴权绑定中间件，这个链路里还有：

- 请求作用域中间件：为 request context 和日志提供上下文。
- payload guard：保护请求体边界。
- security header：补充安全响应头。
- elapsed probe / access log：记录请求耗时和访问日志。

**五、应用层的功能**

应用层是鉴权业务的核心执行层。它把“HTTP 请求”变成“有明确输入输出和事务边界的业务动作”。

主要包含三个用例。

`IssueAccessTokenUsecase` 的完整功能是：

- 对登录请求做节流检查，防止暴力尝试。
- 根据用户名查询用户身份快照。
- 校验用户是否存在、是否允许登录、是否启用。
- 使用密码哈希器校验明文密码。
- 如果密码哈希算法已过时，则在成功登录后触发重哈希更新。
- 生成 access token 和 refresh token。
- 生成对应的 refresh token session 持久化记录。
- 成功后清理失败计数，失败时记录失败计数。
- 最终返回 token 签发结果。

`RefreshAccessTokenUsecase` 的完整功能是：

- 对 refresh 请求做节流检查。
- 解码并校验 refresh token。
- 通过 token id 在数据库中锁定原 refresh token 记录。
- 判断该 token 是否存在、是否已撤销、是否已轮换、是否发生 reuse。
- 如果检测到 refresh reuse，则执行更强的失效策略，通常是吊销整条 token session。
- 如果 token 合法，则读取当前用户身份和授权真值。
- 生成新的一对 access/refresh token。
- 把旧 refresh token 标记为 rotated，并插入新的 refresh session 记录。
- 清理或记录失败计数。
- 返回新的签发结果。

`RevokeTokenSessionUsecase` 的完整功能是：

- 解码 refresh token。
- 找到对应的 token session。
- 将 session 标记为撤销。
- 返回撤销结果。

它的实际语义更准确地说是“撤销 token session”，因为 access token 自身通常不是单独落库的；真正控制 access token 继续是否可用的，是该 access token 所关联的 session 是否还被视为存活。

**六、端口层的功能**

`src/application/ports` 这一层的意义是“把应用层需要的能力抽象出来，而不是直接依赖基础设施实现”。

其中最核心的是 `AuthRuntimePort`。它定义应用层需要以下能力：

- 获取节流器。
- 创建事务单元 UoW。
- 创建认证身份仓储。
- 创建 refresh token 仓储。
- 获取密码哈希器。
- 获取 JWT 服务。

它的作用有两个：

1. 让 usecase 写法稳定，不依赖具体实现类。
2. 让测试时可以替换成假实现或测试实现。

`application_port_contract.py` 则更偏“整套应用暴露了哪些 port，以及它们的启用状态是什么”的总契约描述。它属于装配和声明层，而不是主业务执行层。

**七、核心契约层的功能**

`src/core/auth_contract` 和 `src/core/persistence_contract` 是整套鉴权体系的稳定语义中心。

`core/auth_contract` 主要定义以下内容：

- `AuthenticatedPrincipal`：当前已认证主体长什么样，里面通常包括 subject、用户名、角色、scope、token/session 信息。
- `AuthorizationPolicy` 和路由要求对象：描述某个接口要求哪些角色、哪些 scope。
- `AuthIdentityAuthorizationSnapshot`：从数据库读出来的“某个用户当前实际拥有哪些角色和 scope”的快照。
- `TokenPayload`：JWT 里有哪些关键字段，比如 subject、jti、sid、token_use、exp；其中 jti 和 sid 在契约层已收紧为 UUID 语义，非法格式会在 JWT 解码阶段归一为 token invalid。
- `TokenIssuePayload`：签发 token 后给上层的标准结果。
- `TokenRevokePayload`：撤销后的标准结果。
- `TokenSessionStatusPayload`：session 当前状态查询结果。
- `RefreshTokenInvalidationCommand`：要失效哪些 refresh session 的命令表达。
- `AuthThrottleStatePayload`：节流状态快照。
- `BootstrapRoleBinding`：启动时默认角色和 scope 的绑定契约。

这一层的作用是让“认证、授权、token、session、节流”这些核心概念以稳定的、类型化的方式被表达，避免业务代码散落字符串和隐式约定。

`core/persistence_contract` 则定义持久化边界：

- `AuthIdentityRepository` 负责读取用户身份、授权快照、状态信息、更新密码哈希。
- `RefreshTokenRepository` 负责 refresh token session 的创建、查询、加锁读取、轮换标记、会话撤销、批量撤销。
- `UnitOfWork` 定义事务边界。
- `Repository` 定义基础仓储接口。

这层的作用是让应用层知道“需要什么持久化能力”，但不用知道“数据库怎么查”。

**八、领域层的功能**

`src/domain/auth` 存放的是最稳定、最业务化、最少依赖实现细节的鉴权语义。

它主要提供：

- `AuthErrorCode`：统一的鉴权错误码语义。
- `AuthRoleKey`：角色键，如管理员、普通用户等。
- `AuthScopeCode`：scope 代码，描述细粒度权限。
- `AccessTokenPolicy`：JWT 策略值对象，封装算法、issuer、audience、TTL 等。

这层的价值在于把“系统到底有哪些角色、哪些权限、token 的业务语义是什么”沉淀为统一领域语言，而不是让这些定义分散在 usecase、路由或 ORM 里。

**九、基础设施鉴权实现层的功能**

`src/infrastructure/auth` 是把抽象契约变成可运行能力的实现层。

`JwtTokenService` 的完整功能是：

- 按统一策略生成 access token 和 refresh token。
- 在 token payload 中写入 subject、token_use、jti、sid、exp 等字段。
- 解码 token。
- 校验签名、algorithm、issuer、audience、`token_use`、过期时间等。
- 把原始 token 转换成统一的 `TokenPayload`。

`PasswordHasher` 的完整功能是：

- 生成密码哈希。
- 验证密码与哈希是否匹配。
- 判断现有哈希是否需要升级重算。

`OAuth2SchemeProvider` 的完整功能是：

- 从请求头解析 Bearer token。
- 屏蔽与业务无关的 HTTP 头解析细节。

`AuthorizationPolicyEvaluator` 的完整功能是：

- 接收 principal 和授权策略。
- 判断 principal 是否满足所需 roles。
- 判断 principal 是否满足所需 scopes。
- 输出允许或拒绝的授权决定。

`AuthFailureThrottle` 的完整功能是：

- 对登录失败做计数，计数通过缓存层原子递增能力完成。
- 对 refresh 失败做计数，refresh token 原文会先摘要化再参与缓存 key 构建。
- 在达到阈值时拒绝后续尝试。
- 成功后清理失败状态。

当前缓存契约提供 `increment_with_expire` 能力；Redis 实现使用 Lua 包装 `INCR + EXPIRE`，内存实现使用进程内锁，生产配置要求鉴权节流使用分布式缓存并按 fail-closed 处理缓存不可用。

`BootstrapAdminSynchronizer` 的完整功能是：

- 在启动阶段检查 bootstrap admin 是否应存在。
- 若应存在，则确保管理员用户存在。
- 确保管理员角色存在。
- 确保角色与 scope 的默认绑定存在。
- 确保管理员用户与管理员角色建立关系。

换句话说，这一层提供了整套鉴权系统真正可运行的技术能力：签 token、验 token、验密码、算授权、做节流、做初始身份同步。

**十、持久化层的功能**

`src/infrastructure/persistence` 负责把鉴权数据落到数据库，并从数据库读回真值。

`AuthIdentityRepositoryImpl` 的完整职责是：

- 通过用户名查询用户身份。
- 通过 subject_id 查询用户身份。
- 查询用户当前授权快照，包括角色和 scope。
- 查询用户状态，例如是否激活、是否禁用。
- 更新密码哈希。

它对应的是“身份真值”和“授权真值”。

`RefreshTokenRepositoryImpl` 的完整职责是：

- 创建 refresh token session 记录。
- 按 token id 查询 refresh token。
- 在 refresh 时使用 `for update` 锁定原 token 行，保证轮换和 reuse 检测的事务一致性。
- 查询某个 session 当前是否撤销、是否过期、是否存在不一致状态、是否仍为有效链路。
- 把某个 refresh token 标记为 rotated。
- 撤销某个 token session。
- 在检测到 refresh reuse 等风险时批量吊销会话。

它对应的是“会话生命周期真值”。

ORM 模型则分别承载：

- 用户表。
- 角色表。
- 角色与 scope 绑定表。
- 用户与角色绑定表。
- refresh token session 表。

它们共同定义了整套鉴权数据模型：谁是用户、用户拥有哪些角色、角色拥有哪些 scope、有哪些 refresh session 存在、哪些 session 已撤销或已轮换。当前 refresh token session 表还通过外键约束关联用户 subject，并通过自关联外键约束 `rotated_to_token_id` 指向新的 refresh token 记录。

**十一、鉴权真实工作方式**

这套系统的关键点在于它把“认证”和“授权”拆开了。

认证的工作方式是：

- 请求带 Bearer token 进来。
- 中间件验签、读 token payload、识别 subject 和 session。
- 如果 token 合法且关联的用户状态、session 状态都允许，并且 session 未过期、未撤销、未处于不一致状态，则生成一个 `AuthenticatedPrincipal`。

授权的工作方式是：

- 受保护路由通过依赖明确要求某些角色和 scope。
- `AuthorizationGuard` 调用策略评估器判断当前 principal 是否满足。
- 满足则继续执行，不满足则返回 403。

也就是说：

- token 本身证明“这是谁发的、给谁发的、是否过期、属于哪条 session”。
- 数据库证明“这个人现在是否还拥有这些角色和权限”。
- refresh token session 表证明“这条会话现在是否仍然被承认”。

这就是它比单纯 JWT 方案更强的地方：角色变更、权限回收、session 撤销都可以在服务端即时生效，而不必等 access token 自然过期。

**十二、几个关键链路的完整功能说明**

登录链路的完整功能是：验证用户身份、签发 token、建立 refresh session，并把这次成功登录变成一条服务端可追踪、可撤销、可轮换的会话。

刷新链路的完整功能是：把原 refresh token 所代表的旧会话节点推进到新节点，同时检测旧 token 是否被重放。如果发现重放，则认为整条会话不再可信，直接熔断。

撤销链路的完整功能是：把某条 session 从服务端真值上标记为失效，使得与该 session 关联的后续 access/refresh 使用都不再被承认。

受保护请求链路的完整功能是：识别当前用户、读取其当前真实授权、确认会话仍有效，然后再让业务 handler 执行。

**十三、这套体系的工程意义**

从工程角度看，这套鉴权体系的完整价值可以概括为：

- API 层负责边界适配。
- 中间件层负责认证上下文绑定。
- 应用层负责登录、刷新、撤销等业务动作。
- 契约层负责统一核心概念。
- 领域层负责稳定业务语义。
- 基础设施层负责 JWT、密码、节流、仓储等技术实现。
- 持久化层负责身份真值、授权真值和 session 真值。
- 装配层负责把这些能力在启动时组装起来。

如果用一句话总结它的完整功能：它实现的是一套“可签发、可刷新、可撤销、可回收权限、可做会话熔断、并且依赖数据库维护授权真值”的服务端鉴权系统。
