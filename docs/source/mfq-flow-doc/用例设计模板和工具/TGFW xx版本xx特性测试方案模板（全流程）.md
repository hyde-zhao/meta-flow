## 首页
| Unnamed: 0 | Unnamed: 1 | Unnamed: 2 | Unnamed: 3 | Unnamed: 4 | Unnamed: 5 | Unnamed: 6 | Unnamed: 7 | Unnamed: 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NGFW\_V60R001C00 \nQoS特性测试方案 | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 拟定 | 赵海波 | NaN | 日期 | 2022-07-12 00:00:00 | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 审核 | NaN | NaN | 日期 | XXXX/XX/XX | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 批准 | NaN | NaN | 日期 | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 修订记录 | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 日期 | 修订版本 | 修改记录 | NaN | NaN | NaN | 修改人 |
| NaN | NaN | 2022-07-12 00:00:00 | V1.0 | 初稿输出 | NaN | NaN | NaN | 赵海波 |

## 特性概述
| 被测特性概述 | Unnamed: 1 |
| --- | --- |
| NaN | 被测特性概述是对“被测特性”本身情况说明，目的在于让读者对被测对象备有一个基本认识。其内容建议包括：\n（1）被测对象的历史背景；\n（2）被测对象（版本/特性）的市场定位和市场应用说明；\n（3）概括说明被测对象实现架构/处理流程；\n（4）限制和其他特殊说明。\n概述部分描述特性的背景，包括特性的主要外在功能表现，开发本特性的背景，特性主要的应用场景等。\n这部分的描述主要是让阅读者尽快抓住特性的核心内容，了解对于这个特性，需要首要保证的、最基本的是哪些内容。\n\n带宽管理指的是FW基于入接口/源安全区域、出接口/目的安全区域、源地址/地区、目的地址/地区、用户、服务、应用、URL分类、时间段和报文DSCP优先级信息，对通过自身的流量进行管理和控制。\n\n带宽管理提供带宽限制、带宽保证和连接数限制功能，可以提高带宽利用率，避免带宽耗尽。\n•带宽限制：限制网络中非关键业务占用的带宽，避免此类业务消耗大量带宽资源，影响其他业务。\n•带宽保证：保证网络中关键业务所需的带宽，当线路繁忙时，确保此类业务不受影响。\n•连接数限制（包括并发连接数限制和每秒新建连接速率限制）\n\n限制业务的连接数，有利于降低该业务占用的带宽，还可以节省设备的会话资源。\n在FW上部署带宽管理，可以帮助网络管理员合理分配带宽资源，从而提升网络运营质量。 |
| 被测特性测试方案概述 | NaN |
| NaN | 测试方案概述是对“测试方案”文档的说明，目的在于让读者对测试方案总体思路和文档结构有一个基本的认识。其内容建议包括：\n（1）测试文档写作目的说明，如提供总体测试方案、提供全面特性测试方案、提供组网业务验证测试方案；\n（2）测试思路概要说明，说明测试设计的主要方法和思路；\n（3）测试文档内容说明，说明本测试文档的包括主要内容，文档框架；\n（4）限制和其他特殊说明。\n该测试方案描述TGFW 带宽管理特性测试方案。\n主要包含策略匹配、带宽限制、带宽保证和连接数量限制等功能 |

## 特性场景分析
| 应用场景名 | Unnamed: 1 | 通过最大带宽和保证带宽，对企业实施带宽管理 |
| --- | --- | --- |
| 场景编号 | NaN | QoS.Bandwidth.cir&pir |
| 场景描述 | 主场景 | 带宽管理的基本使用场景如图1所示。在企业日常办公环境中，Email、ERP等流量可以认为是关键业务流量；而P2P、在线视频等流量可以认为是非关键业务流量。管理员经常面临企业的有限带宽长时间被非关键业务流量占据，而关键业务的流量却无法得到保证，导致正常业务受到影响，引起投诉。\nFW提供的整体最大带宽限制和整体带宽保证功能，可以有效限制企业非关键业务流量占用的带宽，而且可以针对关键业务的流量进行保证，确保可以在流量高峰时段正常转发。同时，通过最大连接数限制，也可以在P2P流量控制过程中起到辅助作用。 |
| NaN | 扩展场景 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 1、预先配置带宽（接口和通道）和带宽策略，首次安全后带宽策略和带宽限制能够生效 |
| NaN | 扩容 | 1、增加接口和通道的带宽，包括速率和总额\n2、增加通道的数量和在新的接口上启用带宽管理功能\n3、增加带宽策略的数量\n4、增加带宽策略的类型（包括五元组和应用） |
| NaN | 维护 | 1、查看带宽管理监控数据包括：各通道的速率，流量，连接数，连接速率显示，转发的报文数，丢包数量\n2、查看带宽管理日志(限额日志、操作日志） |
| NaN | 可靠性和性能 | 1、反复修改、增删和查询带宽（接口和通道）和带宽策略，后观察带宽限制和连接数量限制是否生效\n2、开启带宽管理后对转发性能的影响符合预期值\n3、带宽限制和连接的限制的精度符合预期值 |
| NaN | 易用性 | 1、配置失败时的错误码返回信息\n2、监控数据和日志信息的易读性 |
| 用户使用习惯 | 配置顺序 | 1、配置接口带宽->配置通道->配置带宽策略\n2、配置通道->配置带宽策略->配置接口带宽 |
| NaN | 正常操作 | 1、修改和删除未引用（包括未被引用过的和取消引用的）的带宽通道\n2、修改被带宽策略引用的对象 |
| NaN | 错误（异常）操作 | 1、不允许修改和删除被引用的带宽通道\n2、不允许删除被带宽策略引用的对象 |
| NaN | NaN | NaN |
| 应用场景名 | NaN | 通过每IP/每用户最大带宽，对内网的每IP地址或每用户实施带宽管理 |
| 场景编号 | NaN | QoS.Bandwidth.per\_private\_Ip |
| 场景描述 | 主场景 | 如图所示，企业内网员工通过源NAT方式访问互联网，同时企业内网服务器使用NAT Server方式对外提供访问服务。由于企业出口带宽有限，而少数用户却占用了大多数的带宽资源，对外提供服务的某些内网服务器也占用了较大的带宽，这些问题都严重影响了企业正常运作。\nFW提供的带宽管理功能，在源NAT或者服务器映射（NAT Server）场景下，可以配置每个员工能够使用的最大带宽资源或者每服务器对外可提供的最大带宽资源，从而实现细粒度的带宽管控。 |
| NaN | 扩展场景 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 同上 |
| NaN | 扩容 | 1、内网用户IP数量增加后带宽管理能够正确生效 |
| NaN | 维护 | 同上 |
| NaN | 可靠性和性能 | 1、增删修改Nat策略后带宽限制和连接限制能够正确按照配置进行工作 |
| NaN | 易用性 | 同上 |
| 用户使用习惯 | 配置顺序 | 1、现在配置Nat再配置带宽管理\n2、先在配置带宽管理再配置Nat |
| NaN | 正常操作 | 同上 |
| NaN | 错误（异常）操作 | 同上 |
| NaN | NaN | NaN |
| 应用场景名 | NaN | 通过公网IP地址匹配，对源NAT映射后或服务器映射前的公网IP地址实施带宽管理 |
| 场景编号 | NaN | QoS.Bandwidth.per\_Public\_Ip(不支持) |
| 场景描述 | 主场景 | 如图3所示，企业内网员工通过源NAT方式访问互联网，同时企业内网服务器使用NAT Server方式对外提供访问服务。由于企业出口带宽有限，管理员只想对某些公网IP地址的带宽进行限制，不关注内网每个员工或服务器的带宽占用。\nFW提供的带宽管理功能，在源NAT或者服务器映射（NAT Server）场景下，可以对源NAT转换后或NAT Server转换前的公网IP地址进行带宽限制，实现对带宽资源的整体管控。 |
| NaN | 扩展场景1 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 同上 |
| NaN | 扩容 | 1、公网用户IP数量增加后带宽管理能够正确生效 |
| NaN | 维护 | 同上 |
| NaN | 可靠性和性能 | 1、增删修改Nat策略后带宽限制和连接限制能够正确按照配置进行工作 |
| NaN | 易用性 | 同上 |
| 用户使用习惯 | 配置顺序 | 1、现在配置Nat再配置带宽管理\n2、先在配置带宽管理再配置Nat |
| NaN | 正常操作 | 同上 |
| NaN | 错误（异常）操作 | 同上 |
| NaN | NaN | NaN |
| 应用场景名 | NaN | 通过多级父子策略，对部门及部门下指定员工和业务实施带宽管理 |
| 场景编号 | NaN | QoS.policy.father\_son（不支持） |
| 场景描述 | 主场景 | 如图所示，企业下划分部门A和部门B，部门A下划分销售员工和研发员工。为了实现对现有带宽资源进行多层次的管控，不仅对部门A和部门B进行带宽限制，还要分别对部门A下的销售员工和研发员工进行带宽限制。与此同时，为了确保部门A销售员工的业务能够正常开展，还要保证邮件、ERP等关键应用流量能够在流量高峰期正常转发。\nFW提供的带宽管理功能，可以通过多级父子策略来实现对部门及部门下指定员工和业务实施带宽管理。 |
| NaN | 扩展场景1 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 同上 |
| NaN | 扩容 | 同上 |
| NaN | 维护 | 同上 |
| NaN | 可靠性和性能 | 同上 |
| NaN | 易用性 | 同上 |
| 用户使用习惯 | 配置顺序 | 1、建立父策略后再建立子策略 |
| NaN | 正常操作 | 同上 |
| NaN | 错误（异常）操作 | 1、已经建立的策略不能再配置父策略\n2、被引用的父策略不能删除和修改 |
| NaN | NaN | NaN |
| 应用场景名 | NaN | 通过共享带宽通道，对同一对象实施多维度带宽管理 |
| 场景编号 | NaN | QoS.channel.share |
| 场景描述 | 主场景 | 如图5所示，企业下划分部门A和部门B。现需要对部门A和部门B分别进行带宽管控。同时，由于该企业的P2P应用带宽较大，还需要对部门A和部门B共用的P2P应用带宽之和进行限制。\nFW提供的带宽管理功能，管理员可以通过配置共享型的带宽通道，既能让各个部门拥有独立的带宽策略，又能跨部门对P2P流量进行带宽限制，实现多维度的带宽管理。 |
| NaN | 扩展场景1 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 同上 |
| NaN | 扩容 | 共享带宽的流(用户、五元组、应用等)增加后带宽管理仍然能够正确工作 |
| NaN | 维护 | 同上 |
| NaN | 可靠性和性能 | 同上 |
| NaN | 易用性 | 同上 |
| 用户使用习惯 | 配置顺序 | 同上 |
| NaN | 正常操作 | 同上 |
| NaN | 错误（异常）操作 | 同上 |
| NaN | NaN | NaN |
| 应用场景名 | NaN | 通过动态均分方式，为每个用户平均分配带宽资源（不支持） |
| 场景编号 | NaN | QoS. |
| 场景描述 | 主场景 | 如图6所示，企业某部门的在线用户数不固定且浮动较大，为了避免有限的带宽资源被某些员工独占，管理员需要根据实际的在线用户数动态平均分配带宽资源，确保带宽使用的公平性。\nFW提供的带宽管理功能，管理员可以为所有员工配置整体最大带宽，再根据在线IP数或者用户数动态计算每用户可获得的最大带宽资源。 |
| NaN | 扩展场景1 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 同上 |
| NaN | 扩容 | 用户数量增加后均分带宽仍然能够正确工作 |
| NaN | 维护 | 同上 |
| NaN | 可靠性和性能 | 同上 |
| NaN | 易用性 | 同上 |
| 用户使用习惯 | 配置顺序 | 同上 |
| NaN | 正常操作 | 同上 |
| NaN | 错误（异常）操作 | 同上 |
| NaN | NaN | NaN |
| 应用场景名 | NaN | 通过接口带宽，对GRE隧道两端的Tunnel接口流量实施带宽管理 |
| 场景编号 | NaN | QoS. |
| 场景描述 | 主场景 | 如图7所示，网络1与网络2使用GRE建立隧道。通过接口带宽，可以对GRE隧道两端的Tunnel接口流量实施带宽管理。这种配置方式可以对GRE封装后在公网传输的流量总和进行带宽管控。关于GRE和Tunnel接口的配置，请参见GRE和接口，对Tunnel口的带宽管控，可以通过以下两种方式实现：\n•在“网络 > 接口”下，可以配置Tunnel接口的入方向带宽和出方向带宽。\n•在带宽策略的入接口/出接口匹配条件中引用Tunnel接口，详细配置请参见配置带宽策略。 |
| NaN | 扩展场景1 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 同上 |
| NaN | 扩容 | 同上 |
| NaN | 维护 | 同上 |
| NaN | 可靠性和性能 | 同上 |
| NaN | 易用性 | 同上 |
| 用户使用习惯 | 配置顺序 | 同上 |
| NaN | 正常操作 | 同上 |
| NaN | 错误（异常）操作 | 1、被带宽策略引用后进行tunnel口删除 |
| NaN | NaN | NaN |
| 应用场景名 | NaN | 配额控制策略的应用场景 |
| 场景编号 | NaN | QoS. |
| 场景描述 | 主场景 | 如图1所示，FW作为企业的出口网关，部署在网络边界处。对于企业管理者来说，通常会面临如下问题：\n•由于P2P下载、在线视频等应用的存在，使得少数员工占用了企业几乎全部的带宽资源，导致关键业务无法开展。\n•对于某些通过流量与ISP结算费用的企业来说，P2P下载、在线视频这些应用，采用传统限制带宽的方式，已经无法应对长时间挂机下载、缓冲等逃避方案。\n•员工利用互联网，长时间进行一些娱乐活动，严重影响了工作效率。\n\n针对上述问题，FW提供了配额控制策略功能，可以从上网流量、上网时长两个维度，对员工的上网活动进行合理分配和监控。 |
| NaN | 扩展场景1 | NaN |
| 测试组网 | 主TOPO | NaN |
| NaN | 扩展TOPO | NaN |
| 用户关注点 | 开局部署 | 同上 |
| NaN | 扩容 | 1、增加配额或者增加时长 |
| NaN | 维护 | 同上 |
| NaN | 可靠性和性能 | 同上 |
| NaN | 易用性 | 同上 |
| 用户使用习惯 | 配置顺序 | 同上 |
| NaN | 正常操作 | 同上 |
| NaN | 错误（异常）操作 | 同上 |

## 实现原理
| Unnamed: 0 | Unnamed: 1 |
| --- | --- |
| 特性在系统中的位置 | QoS特性在整个系统中的调用关系 |
| 图示 | NaN |
| 说明 | 如上图, 带宽管理模块根据各自实现的功能分成了限速模块和限连接模块。\n\n限速模块:\n限速模块主要完成带宽相关的管理。从转发的快慢路径上来讲，除首队列的包，其它大量数据包都经过快转路径转发，所以限速模块布置在快转路径上。位置在快转路径上的ip4-rewrite前。\n\n连接数限制模块：\n连接数限制模块主要处理TCP的连接数量和连接速率限制。首队列的包，比如TCP在建立连接后，才会走到快转路径上转发，在快转路径上限制连接已经太晚了，所以连接限制应该处于首包路径上。\n限连接模块不应该限制到内核的协议报文。\n因为安全策略模块可能会丢包，为了限制的准确性，模块处于安全策略之后。但如果想要降低安全策略的压力，可将模块移至安全模块之前，但会丢失连接限制的准确性，这是因为如果模块放置在安全模块之前，连接限制已经放过此连接，但安全模块拦截了此包，那么连接限制模块统计将不准确。\n |
| NaN | NaN |
| NaN | NaN |
| 特性内部实现分析 | QoS特性的内部实现 |
| 简述 | NaN |
| 流程图 | NaN |
| 说明 | 带宽策略：\n    带宽策略定义了被管理的匹配对象，并引用带宽通道。\n带宽通道：\n带宽通道定义了被管理的对象所能够使用的带宽资源，将被带宽策略引用。\n用户通道：\n    用户通道定义了带宽通道内具体用户可以使用的带宽资源，将被带宽通道引用。\n未命中策略：\n未被带宽策略管理的对象。\n剩余通道流量：\n接口带宽在带宽策略对象使用带宽通道后，剩余的带宽流量。\n其它用户：\n处于剩余通道流量下的其它用户。\n\n流量匹配带宽策略，经过带宽策略的分流后，进入相应的带宽通道进行处理。带宽通道的处理包括丢弃超过了预先定义的最大带宽的流量，限制业务的连接数和总额，转发在带宽策略下的数据包。受接口带宽的限制，如果其它用户的包超过接口流量，则会丢包，从而保证带宽策略下的流量转发。\n |

## 需求分析
| 设计需求编号 | 设计需求标题 | 需求说明 | 设计策略 | 功能分析 | 支持设备 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 3.8 服务质量 | 3.8.1 带宽限制 | 1.上下行的带宽速率限制,上下行代表的含义跟带宽策略本身有关：流量传输方向与带宽策略同向时，定义为上行；与带宽策略反向时，定义为下行 | 新增用例 | 1、流量速率限制测试，包括上行和下行流量限制 | NaN | NaN |
| NaN | NaN | 2.上下行的流量总额限制，限额数据需要定时保存 | 新增用例 | 1、流量总额限制测试，包括上行和下行\n2、流量总额定时开启和过时关闭测试\n3、保存周期为1分钟\n4、策略启停会清除总额的统计 | NaN | NaN |
| NaN | NaN | 3.连接数限制，超过限制条件后，满足匹配条件的包将被丢弃 | 新增用例 | 1、独占通道总连接数量限制测试\n2、共享通道总连接数量测试 | NaN | NaN |
| NaN | NaN | 4.新建连速率接限制，超过限制条件后，满足匹配条件的包将被丢弃 | 新增用例 | 1、独占通道新建连接连接速率测试\n2、共享通道新建连接速率测试 | NaN | NaN |
| NaN | NaN | 5.带宽管理的定时启停 | 新增用例 | 1、速率限制定时启停\n2、总额限制的定时启停\n3、连接数量限制的定时启停\n4、新建连接数量的定时启停 | NaN | NaN |
| NaN | NaN | 6.带宽管理的阀值启停 | 新增用例 | 1、速率限制阈值启停\n2、总额限制的阈值启停\n3、连接数量限制的阈值启停\n4、新建连接数量的阈值启停\n5、阈值启停启停接口上的出方向的Qos功能（带宽、连接和总额都受影响）。 | NaN | NaN |
| NaN | NaN | 7.支持父子策略 | 新增用例 | NaN | NaN | 不支持 |
| NaN | NaN | 8.支持独享和共享通道 | 新增用例 | 1、速率限制共享\n2、连接数量限制共享\n3、新建连接速率共享\n4、速率限制独占\n5、连接数量限制独占\n6、新建连接速率独占\n7、接口带宽只能共享 | NaN | NaN |
| NaN | NaN | 9.动态均分带宽 | 新增用例 | NaN | NaN | 不支持 |
| NaN | NaN | 10.支持七元组的速率限制 | 新增用例 | 1、不同出入接口、源目IP、源目端口、协议号的带宽限制、连接限制和新建连接速率限制 | NaN | NaN |
| NaN | NaN | 11.支持基于接口、域、用户、应用的速率限制 | 新增用例 | 1、不同安全域、用户、应用的带宽限制、连接限制和新建连接速率限制\n2、不同接口的速率限制\n3、接口带宽限制支持物理口、聚合口、子接口、bvi、隧道口 | NaN | 域、用户、应用不支持 |
| NaN | NaN | 12.支持带宽保证， | 新增用例 | 1、共享通道下的保障带宽\n2、独占通道下的保障带宽 | NaN | NaN |
| NaN | NaN | 13.带宽管理支持IPV6 | 新增用例 | 1、支持IPv6策略\n2、支持IPv6速率限制\n3、支持IPv6连接数量限制\n4、支持IPv6新建速率限制 | NaN | 不支持 |
| NaN | NaN | 14.支持显示带宽管理监控,包括：各通道的速率，流量，连接数，连接速率显示，转发的报文数，丢包数量 | 新增用例 | 1、带宽管理监控测试，包含各通道的速率，流量，连接数，连接速率显示，转发的报文数，丢包数量 | NaN | 不支持 |
| NaN | NaN | 15.支持保障带宽和共享带宽混合使用： | 新增用例 | 1、保障带宽和最大带宽限制混合使用验证最大带宽限制的同事能够提供保障带宽 | NaN | NaN |
| NaN | NaN | 16.QOS误差定义：误差范围正负10%以内，否则为不满足。 | 新增用例 | 1、在带宽限制测试中添加观察点误差小于10% | NaN | NaN |
| NaN | NaN | 17.支持显示流量限额的日志 | 新增用例 | 1、带宽限额记录日志测试\n2、带宽管理日志测试 | NaN | 不支持 |

## 功能点分析
| 标记 | 四级目录 | 五级目录 | 变更 | 本版本功能说明 | 对应需求 | 测试点 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| . | 配置管理 | NaN | N | NaN | NaN | NaN | NaN |
| .. | NaN | 接口配置 | N | 接口带宽的增删改查 | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 1.上下行的带宽速率限制,上下行代表的含义跟带宽策略本身有关：流量传输方向与带宽策略同向时，定义为上行；与带宽策略反向时，定义为下行 | 1、接口带宽的增加测试（接口、带宽、繁忙阈值、空闲阈值）\n2、接口带宽的修改测试\n3、接口带宽删除和批量删除测试\n4、接口带宽的查询和分页查询测试\n5、接口带宽容量测试\n6、接口带宽的Oplog测试 | NaN |
| .. | NaN | 通道配置 | N | 接口参数的增删改查 | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 8.支持独享和共享通道 | 1、通道的增加测试（名称、模式、上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率）、限流对象、单用户配置（上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率）\n2、通道的修改测试\n3、通道删除和批量删除测试\n4、通道的查询和分页查询测试\n5、通道容量测试\n6、通道的Oplog测试 | NaN |
| .. | NaN | 策略配置 | N | 策略参数的增删改查 | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 10.支持七元组的速率限制\n11.支持基于接口、域、用户、应用的速率限制\n13.带宽管理支持IPV6 | 1、带宽策略的增加测试（状态、名称、上行接口、下行接口、原地址、源地址组、目的地址、目的地址组、服务、服务组、时间对象、通道）\n2、带宽策略的修改测试\n3、带宽策略删除和批量删除测试\n4、带宽策略的查询和分页查询测试\n5、带宽策略容量测试\n6、带宽策略的Oplog测试\n7、带宽策略优先级调整测试（被移动的策略ID、移动到、目标位置策略ID）\n8、带宽策略优先级调整Oplog测试\n9、策略优先级调整只支持put | NaN |
| . | 策略匹配 | NaN | N | NaN | NaN | NaN | NaN |
| .. | NaN | 策略匹配 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 10.支持七元组的速率限制\n11.支持基于接口、域、用户、应用的速率限制 | 1、单策略：单条件下的匹配验证（源接口、源安全域、源地址、目的接口、目的安全域、目的地址、服务、时间、应用、用户）\n2、单策略：多条件下的匹配验证（正交两两匹配、全匹配） | NaN |
| … | NaN | NaN | NaN | NaN | NaN | 1、多策略：单条件下的匹配验证（组合的算法：包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系）\n2、多策略：多条件下的匹配验证（组合的算法：包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系） | NaN |
| .. | NaN | 匹配优先级 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | NaN | 1、默认不进行Qos匹配\n2、自定义策略优先级按添加顺序从高到低测试\n3、调整自定义策略优先级测试（策略最前、指定ID之前、指定ID之后、默认策略之前） | NaN |
| .. | NaN | 策略分析 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | NaN | 1、沟通带宽管理策略使其结果为冲突策略、冗余策略、隐藏策略、可合并策略、空策略、过期策略、忽略策略 | NaN |
| . | 速率限制 | NaN | N | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽保障 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 1.上下行的带宽速率限制,上下行代表的含义跟带宽策略本身有关：流量传输方向与带宽策略同向时，定义为上行；与带宽策略反向时，定义为下行\n5.带宽管理的定时启停\n6.带宽管理的阀值启停\n8.支持独享和共享通道\n16.QOS误差定义：误差范围正负10%以内，否则为不满足。 | 1、独占通道下的保障带宽测试，保障带宽误差小于10%\n2、共享通道下的保障带宽测试，保障带宽误差小于10%\n3、独占通道和共享通道共存时的保障带宽测试\n4、保障带宽的定时启停功能\n5、保障带宽的阈值启停功能（不能触发）\n6、上行和下行保障带宽测试 | NaN |
| .. | NaN | 带宽限制 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 5.带宽管理的定时启停\n6.带宽管理的阀值启停\n8.支持独享和共享通道\n16.QOS误差定义：误差范围正负10%以内，否则为不满足。 | 1、独占通道下的最大带宽测试，最大带宽误差小于10%\n2、共享通道下的最大带宽测试，最大带宽误差小于10%\n3、独占通道和共享通道共存时的最大带宽测试\n4、最大带宽的定时启停功能\n5、最大带宽的阈值启停功能\n6、上行和下行最大带宽测试 | NaN |
| .. | NaN | 总额限制 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 2.上下行的流量总额限制，限额数据需要定时保存\n5.带宽管理的定时启停\n6.带宽管理的阀值启停 | 1、独占通道总额测试，总额误差小于10%\n2、共享通道总额测试，总额误差小于10%\n3、独占通道和共享通道共存时总额测试，总额误差小于10%\n4、上行和下行总额测试\n5、总额定时启停功能\n6、总额阈值启停功能？（需确认） | NaN |
| . | 连接限制 | NaN | N | NaN | NaN | NaN | NaN |
| .. | NaN | 连接数量 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 3.连接数限制，超过限制条件后，满足匹配条件的包将被丢弃\n5.带宽管理的定时启停\n6.带宽管理的阀值启停\n8.支持独享和共享通道 | 1、独占通道连接数量限制测试，总额误差小于10%\n2、共享通道连接数量限制测试，总额误差小于10%\n3、独占通道和共享通道共存时连接数量限制测试，总额误差小于10%\n4、上行和下行连接数量限制测试\n5、连接数量限制定时启停功能\n6、连接数量限制阈值启停功能？（需确认） | NaN |
| .. | NaN | 新建速率 | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 4.新建连速率接限制，超过限制条件后，满足匹配条件的包将被丢弃\n5.带宽管理的定时启停\n6.带宽管理的阀值启停\n8.支持独享和共享通道 | 1、独占通道新建连接速率限制测试，总额误差小于10%\n2、共享通道新建连接速率限制测试，总额误差小于10%\n3、独占通道和共享通道共存时新建连接速率限制测试，总额误差小于10%\n4、上行和下行新建连接速率限制测试\n5、新建连接速率限制定时启停功能\n6、新建连接速率限制限制阈值启停功能？（需确认） | NaN |
| . | DFX | NaN | N | NaN | NaN | NaN | NaN |
| .. | NaN | DFS | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | 14.支持显示带宽管理监控,包括：各通道的速率，流量，连接数，连接速率显示，转发的报文数，丢包数量\n17.支持显示流量限额的日志 | 1、带宽管理升级测试\n2、流量丢弃日志记录测试\n#3、带宽管理监控测试 | NaN |
| .. | NaN | DFR | N | NaN | NaN | NaN | NaN |
| … | NaN | NaN | NaN | NaN | NaN | 1、反复修改增删带宽管理配置（策略启停、接口带宽、带宽策略、通道配置等）\n2、配置导入导出和配置恢复测试 | NaN |

## 形态差异分析
| 基于具体规格，分析不同形态支持情况 | Unnamed: 1 | Unnamed: 2 | Unnamed: 3 | Unnamed: 4 | Unnamed: 5 | Unnamed: 6 |
| --- | --- | --- | --- | --- | --- | --- |
| 标记 | 四级目录 | 五级目录 | J1900 | C236 | EP（E5-2640） | 覆盖策略 |
| . | 配置管理 | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 接口配置 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | 通道配置 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | 策略配置 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| . | 策略匹配 | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略匹配 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | 匹配优先级 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | 策略分析 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| . | 速率限制 | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽保障 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | 带宽限制 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | 总额限制 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| . | 连接限制 | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 连接数量 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | 新建速率 | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| . | DFX | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFS | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |
| .. | NaN | DFR | 支持 | 支持 | 支持 | J1900、i5和C236均为一个等价类 |

## 版本差异分析
| 标记 | 四级目录 | 五级目录 | 版本差异(较上个版本） | 软件改动 | 基础系统改动 | 硬件改动 | 测试点 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| . | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 接口配置 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | 通道配置 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | 策略配置 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| . | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略匹配 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | 匹配优先级 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | 策略分析 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| . | 速率限制 | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽保障 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | 带宽限制 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | 总额限制 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| . | 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 连接数量 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | 新建速率 | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| . | DFX | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFS | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |
| .. | NaN | DFR | 不涉及 | 不涉及 | 不涉及 | 不涉及 | NaN |

## 特性内耦合分析
| 标记 | 五级目录 四级目录        五级目录 | Unnamed: 2 | 接口配置 | 通道配置 | 策略配置 | 策略匹配 | 匹配优先级 | 策略分析 | 带宽保障 | 带宽限制 | 总额限制 | 连接数量 | 新建速率 | DFS | DFR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| . | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 接口配置 | NaN | NaN | 1、接口被引用时可以修改和增删接口带宽 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 通道配置 | NaN | NaN | 1、通道被应用时不能修改和删除通道\n2、通道被取消引用时可以修改和删除通道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略配置 | 1、所有策略的保障带宽之和小于等于接口带宽 | 1、测试配置不能引用不存在的通道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | 1、策略匹配后能够进行带宽保障 | 1、策略匹配后能够进行最大带宽线速 | 1、策略匹配后能够进行总额限制 | 1、策略匹配后能够进行连接数量限制 | 1、策略匹配后能够进行新建连接速率限制 | NaN | NaN |
| .. | NaN | 匹配优先级 | NaN | NaN | 1、多策略存在时按照从上往下的优先级进行匹配\n2、调整策略的顺序能够按照正确的优先级进行匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 速率限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽保障 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、保障带宽和最大带宽混合使用 | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 总额限制 | NaN | NaN | 1、策略启停后总额限制重新计算 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 连接数量 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、连接限制和带宽限制混合使用 | 1、连接限制和总额限制混合使用 | NaN | 1、连接数量和新建速率混合使用 | NaN | NaN |
| .. | NaN | 新建速率 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFS | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFR | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |

## 特性间耦合分析
| 标记 | 三级目录 四级目录-五级目录 | Unnamed: 2 | 物理接口 | 子接口 | bvi接口 | 聚合接口 | 隧道接口 | 二层转发 | 接口对 | IPv4路由 | IPv6路由 | ARP | ND | 策略路由 | ISP路由 | OSPF | RIP | DHCP | DNS | PPPoE | IPSecVpn | SSLVpn | IP隧道 | HA | Bypass | Qos | 黑白名单 | IPMac绑定 | NAT | ASPF | 安全策略 | Ddos | SSL卸载 | 应用识别 | 内容过滤 | URL过滤 | 文件过滤 | WEB过滤 | 防病毒 | 入侵防护 | 资产识别 | 对象管理 | 用户管理 | 接入管理 | 启动恢复 | 系统管理 | 管理员管理 | 虚拟系统 | 升级 | SNMP | 授权管理 | 生产 | 会话管理 | 流量统计 | 报表中心 | 日志中心 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| . | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 接口配置 | 1、物理口支持配置接口带宽\n2、物理口与接口最大带宽校验关系 | 1、子接口支持配置接口带宽\n2、配置了接口带宽的子接口不能删除\n3、子接口带宽与挂接口（物理口和聚合口）的带宽校验关系 | 1、bvi接口支持配置接口带宽\n2、配置了接口带宽的bvi接口不能删除\n3、bvi接口带宽与成员口带宽和的校验关系 | 1、聚合口支持配置接口带宽\n2、聚合口的成员口不支持配置带宽。配置带宽的物理口不能加入聚合口\n3、配置了接口带宽的聚合接口不能删除\n4、聚合口带宽与成员口带宽和的校验关系 | 1、隧道口支持配置接口带宽\n2、配置了接口带宽的隧道接口不能删除\n3、隧道口与挂接物理口之间的带宽校验 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、所有的操作都能进行记录操作日志，且日志的操对象和参数、时间正确 |
| .. | NaN | 通道配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、所有的操作都能进行记录操作日志，且日志的操对象和参数、时间正确 |
| .. | NaN | 策略配置 | 1、策略配置可以引用物理口 | 1、策略配置可以引用子接口\n2、被带宽策略引用的子接口不能删除 | 1、策略配置可以引用bvi口\n2、策略配置可以引用bvi口的成员口\n3、被带宽策略引用的bvi接口不能删除 | 1、策略配置可以引用聚合口\n2、策略配置不能引用聚合口的成员口\n3、被带宽策略引用的聚合接口不能删除 | 1、策略配置可以引用隧道口\n2、被带宽策略引用的隧道接口不能删除 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、策略不能引用HA口、管理口等 | NaN | NaN | NaN | NaN | NaN | NaN | 1、被策略引用的安全域可以修改不能被删除 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、被策略引用的地址、地址组、服务、服务组、时间对象可以修改不能删除 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、所有的操作都能进行记录操作日志，且日志的操对象和参数、时间正确 |
| . | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略匹配 | NaN | NaN | NaN | NaN | NaN | 1、二层转发时报文中不包含IP地址可以匹配接口带宽不会匹配任何策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、安全域配置修改后带宽策略匹配能够即时生效 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、地址、地址组、服务、服务组、时间对象配置变化后带宽匹配能够即时生效 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、带宽策略配置时能立即生效\n2、带宽策略修改时能立即生效\n3、带宽策略删除时能立即生效 | NaN | NaN | NaN |
| .. | NaN | 匹配优先级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、调整策略优先级时能立即生效 | NaN | NaN | NaN |
| .. | NaN | 策略分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 速率限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽保障 | 1、不同接口模式（交换、路由、接口对等）下的qos功能（匹配、限速、限额）\n2、物理口的带宽限制功能 | 1、子接口的带宽限制功能 | 1、bvi接口的带宽限制功能 | 1、聚合接口的带宽限制功能 | 1、隧道接口的带宽限制功能 | 1、二层转发下支持带宽保障、带宽限制和总额限制 | 1、接口对时支持带宽保障、带宽限制和总额限制 | 1、IPv4路由转发支持带宽保障、带宽限制和总额限制 | 1、IPv6路由转发支持带宽保障、带宽限制和总额限制 | 1、接口带宽占满时ARP报文能够正常收发？ | 1、接口带宽占满时ND报文能够正常收发？ | NaN | NaN | 1、接口带宽占满时OSPF协议报文能够正常收发？ | 1、接口带宽占满时RIP协议报文能够正常收发？ | 1、接口带宽占满时DHCP报文能够正常收发？ | 1、接口带宽占满时DNS协议报文能够正常收发？ | 1、接口带宽占满时PPPoE报文能够正常收发？\n2、PPPoE接口上的带宽控制 | 1、接口带宽占满时Ipsec协商报文能够正常收发？ | 1、接口带宽占满时用户认证报文能够正常收发 | 1、IP隧道在入隧道的出口物隧道口计算净荷物理口计算封装后的流量\n2、IP隧道在出隧的入口物理口计算封装报文，隧道口计算净荷报文 | NaN | NaN | NaN | 1、黑名单丢弃的报文不占用通道带宽？ | 1、IPMac丢弃的报文不占用通道带宽？ | NaN | NaN | 1、验证Qos带宽限制节点前后的带宽处理差异\n2、验证Qos连接限制节点前后的带宽处理差异 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、接口带宽占满时接入管理报文不收影响？ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 总额限制 | NaN | NaN | 1、流量同时匹配bvi口和bvi成员时的带宽保障、带宽限制和总额限制功能 | NaN | 1、流量同时匹配隧道口和隧道口挂接的物理口的带宽保障、带宽限制和总额限制功能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、手工清除会话、会话老化后总额限制不清除 | NaN | NaN | NaN |
| . | 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | 1、二层转发下支持连接数量限制和新建速率限制 | 1、接口对时支持连接数量限制和新建速率限制 | 1、IPv4路由转发支持连接数量限制和新建速率限制 | 1、IPv6路由转发支持连接数量限制和新建速率限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 连接数量 | 1、不同接口模式（交换、路由、接口对等）下的qos功能（匹配、限制连接）\n1、物理接口的连接限制 | 1、子接口的连接限制 | 1、bvi接口的连接限制\n2、流量同时匹配bvi口和bvi成员连接限制功能 | 1、聚合接口的连接限制 | 1、隧道接口的连接限制\n2、流量同时匹配隧道口和隧道口挂接的物理口的连接限制功能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 新建速率 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFS | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、配置能够正常平滑升级，且无该模块的异常告警 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFR | 1、接口状态变化（UP、Down等）对Qos功能的影响 | 1、子接口增删对带宽和连接限制的影响 | 1、bvi接口增删对带宽和连接限制的影响\n2、bvi的成员口增删对带宽和连接限制的影响 | 1、聚合接口增删对带宽和连接限制的影响\n2、聚合接口的成员口增删对带宽和连接限制的影响 | 1、隧道口增删对带宽和连接限制的影响 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、Qos配置进行主备同步，只能在主设备上配置。备设备不能配置，但可以同步主设备的配置\n2、主备切换之后速率能够正常限制\n3、主主模式，双机均能按照配置的策略进行限速和连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、配置能够在掉电、复位时能够进行配置恢复\n2、配置能够正常进行配置导入、导出 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、带宽策略反复禁用、启用20次时能立即生效\n2、被带宽管理限制的会话显示正确？\n3、被带宽管理开启的会话显示正确？ | NaN | NaN | NaN |

## HTSM分析
| 标记 | HTSM分析维度 四级目录-五级目录 | Unnamed: 2 | 质量标准 | Unnamed: 4 | Unnamed: 5 | Unnamed: 6 | Unnamed: 7 | Unnamed: 8 | Unnamed: 9 | Unnamed: 10 | Unnamed: 11 | Unnamed: 12 | Unnamed: 13 | Unnamed: 14 | Unnamed: 15 | Unnamed: 16 | Unnamed: 17 | Unnamed: 18 | Unnamed: 19 | Unnamed: 20 | Unnamed: 21 | Unnamed: 22 | Unnamed: 23 | Unnamed: 24 | 产品元素 | Unnamed: 26 | Unnamed: 27 | Unnamed: 28 | Unnamed: 29 | Unnamed: 30 | Unnamed: 31 | Unnamed: 32 | Unnamed: 33 | Unnamed: 34 | Unnamed: 35 | Unnamed: 36 | Unnamed: 37 | Unnamed: 38 | Unnamed: 39 | Unnamed: 40 | Unnamed: 41 | Unnamed: 42 | Unnamed: 43 | Unnamed: 44 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NaN | NaN | NaN | 1.功能性 | 2.可靠性 | NaN | NaN | NaN | NaN | NaN | 3.可用性 | NaN | 4.安全性 | NaN | NaN | 5.性能 | 6.可安装性 | NaN | NaN | 7.兼容性 | NaN | NaN | 8.可维护性 | NaN | 9.可测试性 | 1.结构 | 2.功能 | NaN | NaN | NaN | NaN | 3.数据 | NaN | NaN | NaN | NaN | 4.接口 | NaN | 5.操作 | NaN | NaN | 6.时序 | NaN | NaN | NaN |
| NaN | NaN | NaN | 满足功能 | 健壮性 | 数据完整性 | 错误处理 | NaN | NaN | NaN | 可学习性 | 可操作性 | 安全漏洞 | 权限与授权 | 数据保密性 | 速度、反应能力 | 升级/补丁 | 卸载 | 系统要求 | 向后兼容 | 硬件兼容性 | 操作系统兼容性 | 黑匣子 | 维护接口 | NaN | 接口 | 应用 | 计算/算法 | 时间相关 | NaN | 变化/改变 | 预置 | 持久配置项 | 顺序/组合 | 数据规模 | 生命周期 | 用户接口 | 导入导出 | 环境 | 操作顺序 | 极端操作 | 快和慢 | 暂停 | 并发 | NaN |
| NaN | NaN | NaN | 基于规格 | 合理条件下，产品持续运行而不会崩溃或功能失效 | 系统数据应受到保护，防止丢失或被篡改 | 产品有预防错误发生的能力 | 产品发生错误后，有相应的提示或告警 | 产品发生错误后能自愈，恢复后不影响产品运行 | 产品发生错误后能人工恢复，恢复后不影响产品运行 | 通过配套资料能快速使用产品 | 能以最小的付出完成操作（最常用的操作操作路径不超过2层） | 可通过安全漏洞扫描工具的检验 | 已认证的用户拥有被赋予的权限 | 用户数据应受到保护（输入过程中、存储时、传输过程中） | 系统的运行速度、人与设备交互的反应能力 | 是否容易升级新版本或打补丁，是否对已有配置找出影响 | 当特性功能被卸载/不使用后，是否存在配置残留在系统中，影响系统正常运行 | 当系统组件丢失或失效后，产品是否能识别到 | 产品能与老版本协同工作 | 产品与特性硬件协同工作 | 产品与特性操作系统协同工作 | 黑匣子记录能快速支撑产品问题定位 | 产品提供丰富的维护接口，便于产品异常后能快速通过接口接入设备定位 | 产品是否能有效的被测试 | 识别子系统间通讯或连接的点，通过对该点的故障注入，系统是否能识别该故障 | 识别核心功能需求，应重点测试覆盖 | 提取核心算法，设计用例覆盖它 | 系统时间：对特殊时间点的处理是否正确（遇到闰月，闰年是否正确跳转等） | 特性计数器：计数器在极端情况下，精准度是否在规定的误差范围内（CPU过载情况下，2小时PRBS测试是否按时结束） | 识别特性内或特性间存在联动的数据，设计场景覆盖它 | 默认值 | 任何内置的，并被多个操作持续使用的数据，像记录、状态，验证其正确性 | 在合法范围内，识别数据的任何顺序或排列，设计用例覆盖它 | 数据存储规格上限测试（最大OPLOG记录条数） | 必须覆盖数据在生成、读取、修改、删除时的正确处理 | Web、API、NMS | 提供数据导出功能、数据导入功能（正常数据、异常数据、非配套数据等） | 产品适应在不同环境下运行 | 合法的不同操作顺序，系统能正确处理；设计场景覆盖它 | 具有挑战性的输入形式或顺序，设计场景覆盖它 | 以最快的速度、最慢的速度、快慢结合的速度操作 | 在一系列操作中，某个步骤暂停较长时间后再往下操作 | 多用户同时操作同一设备 | 寻求开发获取涉及信号量申请与释放的操作，设计场景触发频繁并发，验证系统是否存在信号量互锁的情况 |
| . | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 接口配置 | NaN | NaN | NaN | NaN | 1、接口配置失败后提示信息正确 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、批量删除和配置接口带宽的响应时间 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | #无默认值 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 通道配置 | NaN | NaN | NaN | NaN | 1、通道配置失败后提示信息正确 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、批量删除和配置通道的响应时间 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | #无默认值 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略配置 | NaN | NaN | NaN | NaN | 1、策略配置失败后提示信息正确 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、批量删除和配置策略的响应时间 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | #无默认值 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略匹配 | 1、最大数量的带宽策略匹配功能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 匹配优先级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 速率限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽保障 | 1、接口线速的保障\n2、设备最大吞吐率的报站 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、先配置接口带宽，在配置通道和略后带宽限制和总额限制生效\n2、先配置通道和策略、再配置接口带宽后带宽限制和总额限制生效 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 总额限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 连接数量 | 1、设备最大数量的连接限制功能？ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、先配置接口带宽，在配置通道和略后连接限制生效\n2、先配置通道和策略、再配置接口带宽后连接限制生效 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 新建速率 | 1、设备最大数量的新建连接速率限制功能？ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFS | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFR | 1、最大数量通道的带宽限制和连接限制功能 | 1、反复修改接口带宽后阈值启停功能正常（带宽限制和连接限制功能正常）\n2、反复调整策略优先级，能够按照正确的优先级匹配\n3、反复增删通道、增删策带宽策略后带宽限制和连接限制功能正常\n4、反复启停和修改策略带宽限制和连接限制功能正常 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1、qos功能开启，大流量时对系统性能的影响\n2、qos功能开启，大流量会话量时对系统性能影响 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |

## 测试点整合
| 标记 | 四级目录 | 五级目录 | 测试点 | \*设计策略 | \*归纳整理后的测试点 | 测试数据 | Unnamed: 7 | Unnamed: 8 | Unnamed: 9 | Unnamed: 10 | Unnamed: 11 | Unnamed: 12 | Unnamed: 13 | Unnamed: 14 | 设计用例 | 合并 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| . | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 接口配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口带宽的增加测试（接口、带宽、繁忙阈值、空闲阈值） | 设计用例 | 接口带宽增加测试 | 接口、带宽、繁忙阈值、空闲阈值、心跳口、管理口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、接口带宽的修改测试 | 设计用例 | 接口带宽修改测试 | 接口、带宽、繁忙阈值、空闲阈值 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、接口带宽删除和批量删除测试 | 设计用例 | 接口带宽删除和批量删除测试 | 删除、批量删除 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、接口带宽的查询和分页查询测试 | 设计用例 | 接口带宽的查询和分页查询测试 | 查询、分页查询 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、接口带宽容量测试 | 设计用例 | 接口带宽容量测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、接口带宽的Oplog测试 | 设计用例 | 接口带宽的Oplog测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口被引用时可以修改和增删接口带宽 | 设计用例 | 接口带宽配置限制测试 | 物理接口,子接口、聚合口、bvi接口、隧道口、PPPoE | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、物理口支持配置接口带宽 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、子接口支持配置接口带宽 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、bvi接口支持配置接口带宽 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、聚合口支持配置接口带宽 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、聚合口的成员口不支持配置带宽。配置带宽的物理口不能加入聚合口 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、隧道口支持配置接口带宽 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、所有的操作都能进行记录操作日志，且日志的操对象和参数、时间正确 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口配置失败后提示信息正确 | 合并 | 接口带宽增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、批量删除和配置接口带宽的响应时间 | 设计用例 | 接口带宽配置响应时间测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 通道配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、通道的增加测试（名称、模式、上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率）、限流对象、单用户配置（上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率） | 设计用例 | 通道增加测试 | 名称、模式、上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率）、限流对象、单用户配置（上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率） | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、通道的修改测试 | 设计用例 | 通道修改测试 | 名称、模式、上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率）、限流对象、单用户配置（上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率） | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、通道删除和批量删除测试 | 设计用例 | 通道删除和批量删除测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、通道的查询和分页查询测试 | 设计用例 | 通道查询和分页查询测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、通道容量测试 | 设计用例 | 通道容量测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、通道的Oplog测试 | 设计用例 | 通道Oplog测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、通道被应用时不能修改和删除通道 | 设计用例 | 通道配置限制测试 | 被应用和取消引用 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、通道被取消引用时可以修改和删除通道 | 合并 | 通道增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、所有的操作都能进行记录操作日志，且日志的操对象和参数、时间正确 | 合并 | 通道增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、通道配置失败后提示信息正确 | 合并 | 通道增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、批量删除和配置通道的响应时间 | 设计用例 | 通道配置响应时间测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、带宽策略的增加测试（状态、名称、上行接口、下行接口、原地址、源地址组、目的地址、目的地址组、服务、服务组、时间对象、通道） | 设计用例 | 带宽策略增加测试 | 状态、名称、上行接口、下行接口、原地址、源地址组、目的地址、目的地址组、服务、服务组、时间对象、通道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、带宽策略的修改测试 | 设计用例 | 带宽策略修改测试 | 状态、名称、上行接口、下行接口、原地址、源地址组、目的地址、目的地址组、服务、服务组、时间对象、通道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、带宽策略删除和批量删除测试 | 设计用例 | 带宽策略删除和批量删除测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、带宽策略的查询和分页查询测试 | 设计用例 | 带宽策略查询和分页查询测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、带宽策略容量测试 | 设计用例 | 带宽策略容量测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、带宽策略的Oplog测试 | 设计用例 | 带宽策略Oplog测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 7、带宽策略优先级调整测试（被移动的策略ID、移动到、目标位置策略ID） | 设计用例 | 带宽策略优先级调整测试 | 被调整ID、方式、目标ID | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 8、带宽策略优先级调整Oplog测试 | 设计用例 | 带宽策略优先级调整Oplog | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、所有策略的保障带宽之和小于等于接口带宽 | 设计用例 | 带宽策略配置限制测试 | 带宽限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、测试配置不能应用不存在的通道 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略配置可以引用物理口 | 设计用例 | 接口引用测试 | 物理口、子接口、bvi、聚合口、隧道口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略配置可以引用子接口 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略配置可以引用bvi口 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、策略配置可以引用bvi口的成员口 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略配置可以引用聚合口 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、策略配置不能引用聚合口的成员口 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略配置可以引用隧道口 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、被策略引用的安全域可以修改不能被删除 | 设计用例 | 策略与对象耦合测试 | 地址、地址组、服务、服务组、时间对象、安全域 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、被策略引用的地址、地址组、服务、服务组、时间对象可以修改不能删除 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、所有的操作都能进行记录操作日志，且日志的操对象和参数、时间正确 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略配置失败后提示信息正确 | 合并 | 带宽策略增加测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略优先级调整只支持put | 设计用例 | 策略优先级调整限制测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、批量删除和配置策略的响应时间 | 设计用例 | 策略配置响应时间测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、物理口与接口最大带宽校验关系 | 设计用例 | 接口带宽校验测试 | 物理口、子接口、bvi、聚合口、隧道口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、子接口带宽与挂接口（物理口和聚合口）的带宽校验关系 | 合并 | 接口带宽校验测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、bvi接口带宽与成员口带宽和的校验关系 | 合并 | 接口带宽校验测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、聚合口带宽与成员口带宽和的校验关系 | 合并 | 接口带宽校验测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、隧道口与挂接物理口之间的带宽校验 | 合并 | 接口带宽校验测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、单策略：单条件下的匹配验证（源接口、源安全域、源地址、目的接口、目的安全与、目的地址、服务、时间、应用、用户） | 设计用例 | 单策略单条件匹配测试 | 源接口、源安全域、源地址、目的接口、目的安全与、目的地址、服务、时间、应用、用户 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、单策略：多条件下的匹配验证（正交两两匹配、全匹配） | 设计用例 | 单策略多条件匹配测试 | 源接口、源安全域、源地址、目的接口、目的安全与、目的地址、服务、时间、应用、用户 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、多策略：单条件下的匹配验证（组合的算法：包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系） | 设计用例 | 多策略单条件匹配测试 | 包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、多策略：多条件下的匹配验证（组合的算法：包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系） | 设计用例 | 多策略多条件匹配测试 | 包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略匹配后能够进行带宽保障 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略匹配后能够进行最大带宽线速 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略匹配后能够进行总额限制 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略匹配后能够进行连接数量限制 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略匹配后能够进行新建连接速率限制 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、安全域配置修改后带宽策略匹配能够即时生效 | 设计用例 | 对象修改策略匹配生效测试 | 安全域、地址、地址组、服务、服务组、时间对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、地址、地址组、服务、服务组、时间对象配置变化后带宽匹配能够即时生效 | 合并 | 对象修改策略匹配生效测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、带宽策略配置时能立即生效 | 合并 | 对象修改策略匹配生效测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、带宽策略修改时能立即生效 | 合并 | 对象修改策略匹配生效测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、带宽策略删除时能立即生效 | 合并 | 对象修改策略匹配生效测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、最大数量的带宽策略匹配功能 | 设计用例 | 策略匹配容量测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 匹配优先级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、默认不进行Qos匹配 | 设计用例 | Qos策略匹配优先级测试 | 默认不匹配、按照顺序匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、自定义策略优先级按添加顺序从高到低测试 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、调整自定义策略优先级测试（策略最前、指定ID之前、指定ID之后、默认策略之前） | 设计用例 | Qos策略优先级调整测试 | 策略最前、指定ID之前、指定ID之后、默认策略之前 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、多策略存在时按照从上往下的优先级进行匹配 | 合并 | Qos策略匹配优先级测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、调整策略的顺序能够按照正确的优先级进行匹配 | 合并 | Qos策略优先级调整测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、调整策略优先级时能立即生效 | 合并 | Qos策略优先级调整测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 策略分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、沟通带宽管理策略使其结果为冲突策略、冗余策略、隐藏策略、可合并策略、空策略、过期策略、忽略策略 | 设计用例 | 带宽策略分析测试 | 冲突策略、冗余策略、隐藏策略、可合并策略、空策略、过期策略、忽略策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 速率限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽保障 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、独占通道下的保障带宽测试，保障带宽误差小于10% | 设计用例 | 独占通道保障带宽测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、共享通道下的保障带宽测试，保障带宽误差小于10% | 设计用例 | 共享通道保障带宽测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、独占通道和共享通道共存时的保障带宽测试 | 设计用例 | 独占和共享带宽共存时保障带宽测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、保障带宽的定时启停功能 | 设计用例 | 保障带宽定时启停功能测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、保障带宽的阈值启停功能（不能触发） | 设计用例 | 保障带宽阈值启停功能测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、上行和下行保障带宽测试 | 合并 | 独占通道保障带宽测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、保障带宽和最大带宽混合使用 | 设计用例 | 保障带宽和最大带宽混合使用 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、不同接口模式（交换、路由、接口对等）下的qos功能（匹配、限速、限额） | 设计用例 | 不同模式下下接口的匹配和限速 | 交换、路由、接口对、二层、接口对、IPv4 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、物理口的带宽限制功能 | 设计用例 | 不同接口类型的带宽限制功能 | 物理接口、子接口、bvi接口、聚合口、隧道接口、PPPoE | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、子接口的带宽限制功能 | 合并 | 不同接口类型的带宽限制功能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、bvi接口的带宽限制功能 | 合并 | 不同接口类型的带宽限制功能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、聚合接口的带宽限制功能 | 合并 | 不同接口类型的带宽限制功能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、隧道接口的带宽限制功能 | 合并 | 不同接口类型的带宽限制功能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、二层转发下支持带宽保障、带宽限制和总额限制 | 合并 | 不同模式下下接口的匹配和限速 | 二层、接口对、IPv4 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口对时支持带宽保障、带宽限制和总额限制 | 合并 | 不同模式下下接口的匹配和限速 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、IPv4路由转发支持带宽保障、带宽限制和总额限制 | 合并 | 不同模式下下接口的匹配和限速 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、IPv6路由转发支持带宽保障、带宽限制和总额限制 | 删除 | NaN | 暂时不支持 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口带宽占满时ARP报文能够正常收发？ | 设计用例 | 拥塞时的协议报文转发 | ARP、ND、PPPoE、DHCP、DNS、管理报文 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口带宽占满时ND报文能够正常收发？ | 合并 | 拥塞时的协议报文转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口带宽占满时ND报文能够正常收发？ | 合并 | 拥塞时的协议报文转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口带宽占满时PPPoE报文能够正常收发？ | 合并 | 拥塞时的协议报文转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、黑名单丢弃的报文不占用通道带宽？ | 设计用例 | 丢弃报文不占用带宽 | 黑白名单、安全策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、IPMac丢弃的报文不占用通道带宽？ | 合并 | 丢弃报文不占用带宽 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、安全策略丢弃的报文不占用通道带宽？ | 合并 | 丢弃报文不占用带宽 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口带宽占满时接入管理报文不收影响？ | 合并 | 拥塞时的协议报文转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口线速的保障 | 设计用例 | 出口拥塞测试 | 上行拥塞测试、下行拥塞测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、设备最大吞吐率的报站 | 合并 | Qos性能测试 | 出口拥塞 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、先配置接口带宽，在配置通道和略后带宽限制和总额限制生效 | 设计用例 | 带宽保障配置顺序测试 | 先配接口带宽、先配策略和通道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、先配置通道和策略、再配置接口带宽后带宽限制和总额限制生效 | 合并 | 带宽保障配置顺序测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 带宽限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、独占通道下的最大带宽测试，最大带宽误差小于10% | 设计用例 | 独占通道最大带宽限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、共享通道下的最大带宽测试，最大带宽误差小于10% | 设计用例 | 共享通道最大带宽限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、独占通道和共享通道共存时的最大带宽测试 | 设计用例 | 独占和共享通道共存最大带宽限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、最大带宽的定时启停功能 | 设计用例 | 最大带宽限制启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、最大带宽的阈值启停功能 | 设计用例 | 最大带宽限制阈值启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、上行和下行最大带宽测试 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 总额限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、独占通道总额测试，总额误差小于10% | 设计用例 | 独占通道总额限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、共享通道总额测试，总额误差小于10% | 设计用例 | 共享通道总额限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、独占通道和共享通道共存时总额测试，总额误差小于10% | 设计用例 | 独占和共享通道共存总额制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、上行和下行总额测试 | 合并 | 独占通道总额限制测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、总额定时启停功能 | 设计用例 | 总额限制限制阈值启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、总额阈值启停功能？（需确认） | 设计用例 | 总额限制启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、策略启停后总额限制重新计算 | 设计用例 | 总额限制限制数据清除条件测试 | 手动启停、定时启停、阈值启停、会话老化和会话清除不清除 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、流量同时匹配bvi口和bvi成员时的带宽保障、带宽限制和总额限制功能 | 设计用例 | 逻辑口与物理口嵌套匹配后的带宽限制和总额限制测试 | bvi口与bvi的成员口、隧道口与物理口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、流量同时匹配隧道口和隧道口挂接的物理口的带宽保障、带宽限制和总额限制功能 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、手工清除会话、会话老化后总额限制不清除 | 合并 | 总额限制限制数据清除条件测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 连接数量 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、独占通道连接数量限制测试，总额误差小于10% | 设计用例 | 独占通道连接数量限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、共享通道连接数量限制测试，总额误差小于10% | 设计用例 | 共享通道连接数量限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、独占通道和共享通道共存时连接数量限制测试，总额误差小于10% | 设计用例 | 独占和共享通道共存连接数量限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、上行和下行连接数量限制测试 | 合并 | 独占通道连接数量限制测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、连接数量限制定时启停功能 | 设计用例 | 连接数量限制阈值启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、连接数量限制阈值启停功能？（需确认） | 设计用例 | 连接数量限制阈值启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、连接限制和带宽限制混合使用 | 设计用例 | 带宽管理混合使用 | 连接限制、带宽限制、总额限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、连接限制和总额限制混合使用 | 合并 | 带宽管理混合使用 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、连接数量和新建速率混合使用 | 合并 | 带宽管理混合使用 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、不同接口模式（交换、路由、接口对等）下的qos功能（匹配、限制连接） | 设计用例 | 不同接口模式的连接限制 | 交换、路由、接口对、连接数量、新建连接速度 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、物理接口的连接限制 | 设计用例 | 不同接口类型的连接限制 | 物理接口、子接口、bvi接口、聚合口、隧道接口、连接数量、新建连接速度 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、子接口的连接限制 | 合并 | 不同接口类型的连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、bvi接口的连接限制 | 合并 | 不同接口类型的连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、流量同时匹配bvi口和bvi成员连接限制功能 | 删除 | NaN | ？ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、聚合接口的连接限制 | 合并 | 不同接口类型的连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、隧道接口的连接限制 | 合并 | 不同接口类型的连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、流量同时匹配隧道口和隧道口挂接的物理口的连接限制功能 | 删除 | NaN | ？ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、设备最大数量的连接限制功能？ | 合并 | Qos性能测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、先配置接口带宽，在配置通道和略后连接限制生效 | 设计用例 | 连接限制配置顺序测试 | 先配qos策略再配接口阈值启停、现配接口阈值启停再配Qos策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、先配置通道和策略、再配置接口带宽后连接限制生效 | 合并 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | 新建速率 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、独占通道新建连接速率限制测试，总额误差小于10% | 设计用例 | 独占通道新建连接速度限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、共享通道新建连接速率限制测试，总额误差小于10% | 设计用例 | 共享通道新建连接速度限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、独占通道和共享通道共存时新建连接速率限制测试，总额误差小于10% | 设计用例 | 独占和共享通道共存新建连接速度限制测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、上行和下行新建连接速率限制测试 | 合并 | 独占通道新建连接速度限制测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 5、新建连接速率限制定时启停功能 | 设计用例 | 建连接速度限制阈值启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 6、新建连接速率限制限制阈值启停功能？（需确认） | 设计用例 | 建连接速度限制阈值启停测试 | 上行、下行 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、设备最大数量的新建连接速率限制功能？ | 合并 | Qos性能测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| . | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFS | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、带宽管理升级测试 | 设计用例 | Qos升级测试 | Qos匹配、带宽和总额限制、连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、流量丢弃日志记录测试 | 删除 | NaN | 暂时不支持且方案不明确 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、配置能够正常平滑升级，且无该模块的异常告警 | 合并 | Qos升级测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| .. | NaN | DFR | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、反复修改增删带宽管理配置（策略启停、接口带宽、带宽策略、通道配置等） | 设计用例 | Qos可靠性测试 | 策略启停、接口带宽、带宽策略、通道配置增删修改、接口Updown、反复修改阈值、反复调整优先级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、配置导入导出和配置恢复测试 | 设计用例 | Qos配置恢复测试 | 配置导入导出、重启复位 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、接口状态变化（UP、Down等）对Qos功能的影响 | 合并 | Qos可靠性测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、Qos配置进行主备同步，只能在主设备上配置。备设备不能配置，但可以同步主设备的配置 | 设计用例 | Qos主备切换测试 | 配置同步、带宽限制主备切换、连接限制主备切换 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、主备切换之后速率能够正常限制 | 合并 | Qos主备切换测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、主主模式，双机均能按照配置的策略进行限速和连接限制 | 合并 | Qos主备切换测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、配置能够在掉电、复位时能够进行配置恢复 | 合并 | Qos配置恢复测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、配置能够正常进行配置导入、导出 | 合并 | Qos配置恢复测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、带宽策略反复禁用、启用20次时能立即生效 | 合并 | Qos配置恢复测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、被带宽管理限制的会话显示正确？ | 设计用例 | Qos控制会话测试 | qos方形、Qos丢弃、策略启停、自动启停 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、被带宽管理开启的会话显示正确？ | 合并 | Qos控制会话测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、最大数量通道的带宽限制和连接限制功能 | 合并 | Qos性能测试 | 大流量时的吞吐量、大会话量时的吞吐量 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、反复修改接口带宽后阈值启停功能正常（带宽限制和连接限制功能正常） | 合并 | Qos可靠性测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、反复调整策略优先级，能够按照正确的优先级匹配 | 合并 | Qos可靠性测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 3、反复增删通道、增删策带宽策略后带宽限制和连接限制功能正常 | 合并 | Qos可靠性测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 4、反复启停和修改策略带宽限制和连接限制功能正常 | 合并 | Qos可靠性测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 1、qos功能开启，大流量时对系统性能的影响 | 合并 | Qos性能测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ... | NaN | NaN | 2、qos功能开启，大流量会话量时对系统性能影响 | 合并 | Qos性能测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 1、子接口增删对带宽和连接限制的影响 | 设计用例 | 带宽和连接限制接口操作可靠性 | 子接口、bvi口、聚合口、隧道口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 1、bvi接口增删对带宽和连接限制的影响 | 合并 | 带宽和连接限制接口操作可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 2、bvi的成员口增删对带宽和连接限制的影响 | 合并 | 带宽和连接限制接口操作可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 1、聚合接口增删对带宽和连接限制的影响 | 合并 | 带宽和连接限制接口操作可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 2、聚合接口的成员口增删对带宽和连接限制的影响 | 合并 | 带宽和连接限制接口操作可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 1、隧道口增删对带宽和连接限制的影响 | 合并 | 带宽和连接限制接口操作可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |

## 测试点分析
| 四级目录 | 五级目录 | 测试点 | 测试设计方法 | 适用场景 | 用例规模（个） | 测试数据 |
| --- | --- | --- | --- | --- | --- | --- |
| 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接口配置 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 接口带宽增加测试 | 等价类划分&数据组合 | NaN | 4.0 | 接口、带宽、繁忙阈值、空闲阈值 |
| NaN | NaN | 接口带宽修改测试 | 等价类划分&数据组合 | NaN | 4.0 | 接口、带宽、繁忙阈值、空闲阈值 |
| NaN | NaN | 接口带宽删除和批量删除测试 | 直接分析 | NaN | 2.0 | 删除、批量删除 |
| NaN | NaN | 接口带宽的查询和分页查询测试 | 直接分析 | NaN | 2.0 | 查询、分页查询 |
| NaN | NaN | 接口带宽容量测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 接口带宽的Oplog测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 接口带宽配置限制测试 | 直接分析 | NaN | 5.0 | 物理接口,子接口、聚合口、bvi接口、隧道口 |
| NaN | NaN | 接口带宽配置响应时间测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 接口带宽校验测试 | 直接分析 | NaN | 5.0 | 物理口、子接口、bvi、聚合口、隧道口 |
| NaN | 通道配置 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 通道增加测试 | 等价类划分&数据组合 | NaN | 19.0 | 名称、模式、上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率）、限流对象、单用户配置（上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率） |
| NaN | NaN | 通道修改测试 | 等价类划分&数据组合 | NaN | 19.0 | 名称、模式、上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率）、限流对象、单用户配置（上行最大带宽、上行保障带宽、下行最大带宽、下行保障带宽、上行总额、下行总额、最大连接数、新建连接速率） |
| NaN | NaN | 通道删除和批量删除测试 | 直接分析 | NaN | 2.0 | NaN |
| NaN | NaN | 通道查询和分页查询测试 | 直接分析 | NaN | 2.0 | NaN |
| NaN | NaN | 通道容量测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 通道Oplog测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 通道配置限制测试 | 直接分析 | NaN | 2.0 | 被应用和取消引用 |
| NaN | NaN | 通道配置响应时间测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | 策略配置 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 带宽策略增加测试 | 等价类划分&数据组合 | NaN | 13.0 | 状态、名称、上行接口、下行接口、原地址、源地址组、目的地址、目的地址组、服务、服务组、时间对象、通道 |
| NaN | NaN | 带宽策略修改测试 | 等价类划分&数据组合 | NaN | 13.0 | 状态、名称、上行接口、下行接口、原地址、源地址组、目的地址、目的地址组、服务、服务组、时间对象、通道 |
| NaN | NaN | 带宽策略删除和批量删除测试 | 直接分析 | NaN | 2.0 | NaN |
| NaN | NaN | 带宽策略查询和分页查询测试 | 直接分析 | NaN | 2.0 | NaN |
| NaN | NaN | 带宽策略容量测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 带宽策略Oplog测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 带宽策略优先级调整测试 | 直接分析 | NaN | 2.0 | 被调整ID、方式、目标ID |
| NaN | NaN | 带宽策略优先级调整Oplog | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 带宽策略配置限制测试 | 直接分析 | NaN | 6.0 | 带宽限制（带宽和），接口限制（物理接口,子接口、聚合口、bvi接口、隧道口） |
| NaN | NaN | 策略与对象耦合测试 | 直接分析 | NaN | 6.0 | 地址、地址组、服务、服务组、时间对象、安全域 |
| NaN | NaN | 策略优先级调整限制测试 | 直接分析 | NaN | 1.0 | put |
| NaN | NaN | 策略配置响应时间测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 接口引用测试 | 直接分析 | NaN | 5.0 | 物理口、子接口、bvi、聚合口、隧道口 |
| 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 策略匹配 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 单策略单条件匹配测试 | 等价类划分&数据组合 | NaN | 10.0 | 源接口、源安全域、源地址、目的接口、目的安全与、目的地址、服务、时间、应用、用户 |
| NaN | NaN | 单策略多条件匹配测试 | 等价类划分&数据组合 | NaN | 5.0 | 源接口、源安全域、源地址、目的接口、目的安全与、目的地址、服务、时间、应用、用户 |
| NaN | NaN | 多策略单条件匹配测试 | 等价类划分&数据组合 | NaN | 4.0 | 包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系 |
| NaN | NaN | 多策略多条件匹配测试 | 等价类划分&数据组合 | NaN | 4.0 | 包含关系、交叉关系、冲突、半闭区间（上点匹配）、完全无包含关系 |
| NaN | NaN | 对象修改策略匹配生效测试 | 直接分析 | NaN | 6.0 | 安全域、地址、地址组、服务、服务组、时间对象 |
| NaN | NaN | 策略匹配容量测试 | 直接分析 | NaN | 1.0 | NaN |
| NaN | 匹配优先级 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | Qos策略匹配优先级测试 | 直接分析 | NaN | 2.0 | 默认不匹配、按照顺序匹配 |
| NaN | NaN | Qos策略优先级调整测试 | 直接分析 | NaN | 4.0 | 策略最前、指定ID之前、指定ID之后、默认策略之前 |
| NaN | 策略分析 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 带宽策略分析测试 | 直接分析 | NaN | 7.0 | 冲突策略、冗余策略、隐藏策略、可合并策略、空策略、过期策略、忽略策略 |
| 速率限制 | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 带宽保障 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 独占通道保障带宽测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 共享通道保障带宽测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 独占和共享带宽共存时保障带宽测试 | 等价类划分&数据组合 | NaN | 3.0 | 上行、下行 |
| NaN | NaN | 保障带宽定时启停功能测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 保障带宽阈值启停功能测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 保障带宽和最大带宽混合使用 | 直接分析 | NaN | 1.0 | NaN |
| NaN | NaN | 不同模式下下接口的匹配和限速 | 直接分析 | NaN | 3.0 | 交换、路由、接口对、二层（带IP和不带IP）、接口对、IPv4 |
| NaN | NaN | 不同接口类型的带宽限制功能 | 直接分析 | NaN | 5.0 | 物理接口、子接口、bvi接口、聚合口、隧道接口（封装和净荷报文计算） |
| NaN | NaN | 拥塞时的协议报文转发 | 直接分析 | NaN | 6.0 | ARP、ND、PPPoE、DHCP、DNS、管理报文 |
| NaN | NaN | 丢弃报文不占用带宽 | 直接分析 | NaN | 2.0 | 黑白名单、安全策略 |
| NaN | NaN | 出口拥塞测试 | 直接分析 | NaN | 2.0 | 上行拥塞测试、下行拥塞测试 |
| NaN | NaN | 带宽保障配置顺序测试 | 直接分析 | NaN | 2.0 | 先配接口带宽、先配策略和通道 |
| NaN | 带宽限制 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 独占通道最大带宽限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 共享通道最大带宽限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 独占和共享通道共存最大带宽限制测试 | 等价类划分&数据组合 | NaN | 3.0 | 上行、下行 |
| NaN | NaN | 最大带宽限制启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 最大带宽限制阈值启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | 总额限制 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 独占通道总额限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 共享通道总额限制测试 | 等价类划分&数据组合 | NaN | 3.0 | 上行、下行 |
| NaN | NaN | 独占和共享通道共存总额制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 总额限制限制阈值启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 总额限制启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 总额限制限制数据清除条件测试 | 直接分析 | NaN | 4.0 | 手动启停、定时启停、阈值启停、会话老化和会话清除不清除 |
| NaN | NaN | 逻辑口与物理口嵌套匹配后的带宽限制和总额限制测试 | 直接分析 | NaN | 2.0 | bvi口与bvi的成员口、隧道口与物理口 |
| 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 连接数量 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 独占通道连接数量限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 共享通道连接数量限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 独占和共享通道共存连接数量限制测试 | 等价类划分&数据组合 | NaN | 3.0 | 上行、下行 |
| NaN | NaN | 连接数量限制阈值启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 连接数量限制阈值启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 带宽管理混合使用 | 直接分析 | NaN | 3.0 | 连接限制、带宽限制、总额限制 |
| NaN | NaN | 不同接口模式的连接限制 | 直接分析 | NaN | 3.0 | 交换、路由、接口对、连接数量、新建连接速度 |
| NaN | NaN | 不同接口类型的连接限制 | 直接分析 | NaN | 5.0 | 物理接口、子接口、bvi接口、聚合口、隧道接口、连接数量、新建连接速度 |
| NaN | NaN | 连接限制配置顺序测试 | 直接分析 | NaN | 2.0 | 先配qos策略再配接口阈值启停、现配接口阈值启停再配Qos策略 |
| NaN | 新建速率 | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 独占通道新建连接速度限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 共享通道新建连接速度限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 独占和共享通道共存新建连接速度限制测试 | 等价类划分&数据组合 | NaN | 2.0 | 上行、下行 |
| NaN | NaN | 建连接速度限制阈值启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| NaN | NaN | 建连接速度限制阈值启停测试 | 直接分析 | NaN | 1.0 | 上行、下行 |
| DFX | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DFS | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | Qos升级测试 | 直接分析 | NaN | 3.0 | Qos匹配、带宽和总额限制、连接限制 |
| NaN | DFR | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | Qos可靠性测试 | 直接分析 | NaN | 7.0 | 策略启停、接口带宽、带宽策略、通道配置增删修改、接口Updown、反复修改阈值、反复调整优先级 |
| NaN | NaN | Qos配置恢复测试 | 直接分析 | NaN | 2.0 | 配置导入导出、重启复位 |
| NaN | NaN | Qos主备切换测试 | 直接分析 | NaN | 3.0 | 配置同步、带宽限制主备切换、连接限制主备切换 |
| NaN | NaN | Qos控制会话测试 | 直接分析 | NaN | 4.0 | qos放行、Qos丢弃、策略启停、自动启停 |
| NaN | NaN | Qos性能测试 | 直接分析 | NaN | 2.0 | 大流量时的吞吐量、大会话量时的吞吐量 |
| NaN | NaN | 带宽和连接限制接口操作可靠性 | 直接分析 | NaN | 4.0 | 子接口、bvi口、聚合口、隧道口 |

## 工具说明
| 说明 | Unnamed: 1 |
| --- | --- |
| NaN | 1、要使用测试点整合工具，功能点分析、形态差异分析、特性内耦合分析、特性间耦合分析、DFX分析 sheet也的标记必须点\n其中\n一个英文点"."表示四级目录\n两个英文点".."表示五级目录\n三个英文点"..."或者省略号"…"表示正文 |
| NaN | 2、测试点和测试点之间必须使用换行符分隔（Excel快捷键ALT+Enter） |
| NaN | 3、在功能点分析中，三级目录和四级目录必须是单独起一行，测试点也必须是单独的一行。不能和三级四级目录在同一行 |
| NaN | 4、版本差异分析的三级目录必须是单独的一行，测试点和四级目录在同一行，测试点必须写在最后一列 |
| NaN | 5、特性内耦合分析、特性间耦合分析、DFX分析的三级目录必须是单独的一行，测试点和四级目录在同一行，测试点写在四级目录之后 |
| NaN | 6、当测试点中第一个特殊字符为"#"号时，该测试点不导入\n注意：\n（1）、特性目录如果打了#号，每个页签都需要同步打"#"号\n（2）、不支持刷新，测试点导入时需要将测试点整合页面进行删除 |