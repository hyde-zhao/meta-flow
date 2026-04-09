## V60R1C00版本特性树
| 一级目录 | 二级目录 | 三级目录 | 四级目录 | 五级目录 | 特性定义 | 英文名称 | 特性ID | 版本特性 | Unnamed: 9 | 风险等级 | XXX版本特性描述 | 测试责任田 | Unnamed: 13 | 特性 优先级 | Unnamed: 15 | Unnamed: 16 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 变更 | 交付版本 | NaN | NaN | 测试设计 | 测试执行 | NaN | NaN | NaN |
| 网络特性 | NaN | NaN | NaN | NaN | NaN | Network | 1.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接口 | NaN | NaN | NaN | NaN | Intf | 11.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 物理接口 | NaN | NaN | 物理接口即设备硬件提供的实体接口相关的属性配置管理 | Phyintf | 111.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1110.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口配置 | NaN | IntfCfg | 11101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口联动配置 | NaN | IntfLinkCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接口管理 | NaN | 物理接口的配置，以及物理接口工作在高级模式的时的功能 | Mng | 1111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口管理 | NaN | IntfMng | 11111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口联动 | 物理接口的接口联动，物理接口与聚合接口的耦合 | IntfLink | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | 物理接口在交换模式和接口对模式时进行二层交换，在路由模式时进行三层路由转发 | Fwd | 1112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 二层交换 | NaN | Switch | 11121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Routing | 11122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 子接口 | NaN | NaN | 1、子接口就是在一个主接口上配置出来的虚拟的逻辑接口，主要用于实现与多个远端进行通信。\n2、子接口特性支持L2子接口和L3子接口 | SubIntf | 112.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1120.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 子接口配置 | NaN | SubIntf | 11201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接口管理 | NaN | 子接口创建删除、名称、工作模式以及接口绑定等相关功能的配置管理 | IntfMng | 1121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 子接口管理 | NaN | SubMng | 11211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | L3子接口 | NaN | L3子接口路由功能、跨VLAN交换功能，L3子接口能根据配置的IP地址生成直连路由，并根据报文中的VLAN进行流量区分。 | L3Sub | 1122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Routing | 11221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | bvi接口 | NaN | NaN | 1、bvi接口类似华为的VLAN接口，为L2接入L3时使用\n2、bvi接口配置IP地址时具有三层特性的逻辑接口，通过配置bvi接口的IP地址，实现VLAN间互访。\n2、明御不支持该特性 | Bvi | 113.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1130.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | bvi配置 | NaN | bviCfg | 11301.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接口管理 | NaN | bvi接口的创建删除、名称和描述等相关属性的配置管理 | IntfMng | 1131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口管理 | NaN | BviMng | 11311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | 1、bvi口中的接口为二层交换域支持二层转发。\n2、bvi域内的接口可以通过bvi接口的IP地址接入三层转发 | Fwd | 1132.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 二层转发 | NaN | Switch | 11321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | L2接入L3 | NaN | L2tol3 | 11322.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 聚合接口 | NaN | NaN | 随着网络中部署的业务量不断增长，对于全双工点对点链路，单条物理链路的带宽已不能满足正常的业务流量需求。\n如果将当前接口板替换为具备更高带宽的接口板，则会浪费现有的设备资源，而且升级代价较大。如果增加设备间的链路数量，则在作为三层口使用时需要在每个接口上配置IP地址，从而导致浪费IP地址资源。\n此时，可以把多个独立的物理接口绑定在一起作为一个大带宽的逻辑接口使用，即Eth-Trunk接口，既不用替换接口板也不会浪费IP地址资源。 | Trunk | 114.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1140.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口配置 | NaN | TrunkCfg | 11401.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接口管理 | NaN | 接口模式管理，成员管理、LACP协商、主动被 | IntfMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口管理 | 接口模式管理，成员管理、LACP协商、主动被动模式、MAC地址 | TrunkMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | 手工聚合口不运行协议实现业务聚合口，聚合口支持工作在2层模式和三层模式以及高级模式 | Manual | 1141.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 二层转发 | 聚合口作为二层接口的路由转发 | Switch | 11412.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | 聚合口作为路由口的接口转发 | Routing | 11413.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载均衡 | 负载均衡 | LoadBalance | 11415.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 隧道接口 | NaN | NaN | 二层交换主要是指链路层的根据MAC学习转发，以及VLAN的隔离相关功能。 | TnlIntf | 115.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1150.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 隧道口配置 | NaN | TnlIntfCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接口管理 | NaN | NaN | IntfMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 隧道口管理 | NaN | TnlIntfMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | NaN | SeviceFWD | 1151.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | 二层交换主要是指链路层的根据MAC学习转发，以及VLAN的隔离相关功能。 | Routing | 12.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 安全域 | NaN | NaN | NaN | Zone | 116.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1160.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 安全域配置 | NaN | ZoneCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 安全域控制 | NaN | NaN | ZoneCtrl | 1161.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口控制 | NaN | IntfCtrl | 11611.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 二层交换 | NaN | NaN | NaN | NaN | L2FWD | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 二层转发 | NaN | NaN | 二层转发基于SMAC进行学习，基于DMAC进行转发 | Switching | 121.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1210.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 二层配置 | NaN | L2Cfg | 12101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | vlan转发 | NaN | 1、1d网桥转发，采用SVL方式学习MAC地址。在转发过程中屏蔽报文的VLAN字段，MAC学习和转发都不会使用VLAN字段（不同VLAN间的业务是可以互通的，NGFW不支持1d网桥）。\n2、1q网桥转发，通常采用IVL方式学习MAC地址，MAC地址学习为Vid+SMAC，报文转发时也会使用VLAN\_ID+DMAC查找MAC地址进行转发，且不同VLAN之间的业务时不能互通的。\n3、L2接入L3：在网桥中接入的报文DMAC匹配网桥接口的MAC地址时可以接入L3实现路由转发 | Vlan | 1211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | mac转发 | NaN | MacFwd | 12111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | vlan隔离 | NaN | VlanIsolate | 12112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | mac学习 | NaN | 二层转发时根据报文中的smac地址学习，在smac接入的端口变化时进行端口迁移功能 | Fdb | 1212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 动态mac | NaN | Dynamic | 12121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 端口迁移 | NaN | PortMigration | 12122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 接口对 | NaN | NaN | 接口对，即一进一出两个接口。将两个同类型接口组成接口对后，从一个接口进入的流量固定从另一个接口转发出去，不需要查询路由表或MAC地址表。如果进、出接口配置为同一个接口，则从该接口进入的报文经过设备处理后仍然从该接口转发出去。\n在该场景下防火墙能完成安全相关的处理，但是用户感觉不到防火墙的存在 | Pair | 122.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1220.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口对配置 | NaN | Pair | 12201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | 接口对场景下的业务转发和安全功能 | Fwd | 1221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口间转发 | NaN | InterFwd | 12211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 1222.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 状态联动 | NaN | Link | 12221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 12222.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | STP | NaN | NaN | NaN | STP | 13.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | STP配置 | NaN | StpCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | RSTP | NaN | NaN | Rstp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | MSTP | NaN | NaN | Mstp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | IP单播 | NaN | NaN | NaN | 为了实现数据转发，路由器必须有能力建立、刷新路由表，并根据路由表转发数据包。 | IpUnicast | 13.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv4路由 | NaN | NaN | 路由（routing）是指分组从源到目的地时，决定端到端路径的网络范围的进程；指路由设备从一个接口上收到数据包，根据数据包的目的地址进行定向并转发到另一个接口的过程。\n1、华为和深信服支持同时指定下一跳和出接口，明御和山石下一跳和出接口是互斥的 | Ipv4 | 131.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1310.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由配置 | NaN | RouteCfg | 13101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | URPF配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 路由维护 | NaN | 静态路由配置以及路由表到维护，包括静态路由、直连路由 | Fib | 1311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态路由 | 静态路由是需要管理员手工配置的特殊路由，适用于网络拓扑结构简单的网络环境。设备的静态路由功能须实现：\n1、能进行正常配置\n2、正常进行选路和转发\n3、“下一跳”可指定下一跳IP地址或出接口\n4、优先级体现\n5、权重体现 | Static | 13111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 直连路由 | 路由器接口所连接的子网的路由方式称为直连路由，设备的直连路由具备以下要求：\n1、接口启用状态下配置IP地址后，自动生成相应网段的直连路由信息，数据和显示正确\n2、正常进行选路和转发 | Direct | 13112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | 按照路由表进行业务转发，包括匹配静态路由、直连路由和最长匹配原则 | Fwd | 1312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Routing | 13121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 单臂路由 | 单臂路由（router-on-a-stick）是指在路由器的一个接口上通过配置子接口（或“逻辑接口”，并不存在真正物理接口）的方式，实现原来相互隔离的不同VLAN（虚拟局域网）之间的互联互通。 | SingleArm | 13122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 等价路由 | NaN | Ecmp | 13123.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 源进源出 | NaN | SISO | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载均衡 | NaN | LoadBalance | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | URPF | NaN | URPF | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 分片重组 | 发送按照接口MTU分片，接受进行重组，与接口MTU强耦合 | Reassembly | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv6路由 | NaN | NaN | 路由（routing）是指分组从源到目的地时，决定端到端路径的网络范围的进程；指路由设备从一个接口上收到数据包，根据数据包的目的地址进行定向并转发到另一个接口的过程。 | Ipv6 | 132.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1320.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由配置 | NaN | RouteMng | 13201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 路由维护 | NaN | 静态路由配置以及路由表到维护，包括静态路由、直连路由 | Fib | 1321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态路由 | 静态路由是需要管理员手工配置的特殊路由，适用于网络拓扑结构简单的网络环境。设备的静态路由功能须实现：\n1、能进行正常配置\n2、正常进行选路和转发\n3、“下一跳”可指定下一跳IP地址或出接口\n4、优先级体现\n5、权重体现 | Static | 13211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 直连路由 | 路由器接口所连接的子网的路由方式称为直连路由，设备的直连路由具备以下要求：\n1、接口启用状态下配置IP地址后，自动生成相应网段的直连路由信息，数据和显示正确\n2、正常进行选路和转发 | Direct | 13212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | 按照路由表进行业务转发，包括匹配静态路由、直连路由和最长匹配原则 | Fwd | 1322.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Routing | 13221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 单臂路由 | 单臂路由（router-on-a-stick）是指在路由器的一个接口上通过配置子接口（或“逻辑接口”，并不存在真正物理接口）的方式，实现原来相互隔离的不同VLAN（虚拟局域网）之间的互联互通。 | SingleArm | 13222.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 等价路由 | NaN | Ecmp | 13223.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 源进源出 | NaN | SISO | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载均衡 | NaN | LoadBalance | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | URPF | NaN | URPF | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 分片重组 | 发送按照接口MTU分片，接受进行重组，与接口MTU强耦合 | Reassembly | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 13224.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | DFR、DFS |
| NaN | NaN | ARP | NaN | NaN | IP邻居协议，IPv4使用ARP协议，IPv6使用邻居发现协议 | Arp | 133.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1330.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ARP配置 | NaN | Arp | 13300.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | ARP管理 | NaN | 地址解析协议ARP（Address Resolution Protocol）是用来将IP地址解析为MAC地址的协议。 | ArpMng | 1331.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 动态ARP | 学习老化更新等 | DynamicArp | 13311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态ARP | NaN | StaticArp | 13312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ARP扫描 | NaN | Scan | 13315.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | ARP、ND的可靠性、可维护性等 | Mng | 1332.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | ARP和ND的升级功能 | DFX | 13321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | ND | NaN | NaN | IP邻居协议，IPv4使用ARP协议，IPv6使用邻居发现协议 | Nd | 134.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1340.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ND配置 | NaN | Nd | 13400.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | ND表 | NaN | IPv6邻居发现协议，包括静态ND和动态ND | Nd | 1341.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 动态ND | 静态配置IPv6邻居 | Dynamic | 13411.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态ND | 动态邻居学习和老化、路由器发现 | Static | 13412.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NdRa | Nd无状态自动配置 | NdRa | 13413.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ND控制 | 控制全局和接口是否学习Nd | NdCtrl | 13414.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ND扫描 | 扫描网络中存在的Nd?-明御不支持 | NdScan | 13415.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | ARP、ND的可靠性、可维护性等 | Mng | 1342.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | ARP和ND的升级功能 | DFX | 13421.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | Flood攻击 | ARP和ND的防Flood攻击功能 | flood | 13422.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 主动防护 | 主动发送免费ARP | ArpProtection | 13423.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv4策略路由 | NaN | NaN | 策略路由，是一种比基于目标网络进行路由更加灵活的数据包路由转发机制。路由器将通过路由图决定如何对需要路由的数据包进行处理，路由图决定了一个数据包的下一跳转发路由器。 | StrategyRoute | 135.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | 策略路由配置管理，包括策略相关的所有接口的配置\n包括路由接口和优先级调整接口的增删改查，以及批量查询和删除接口 | Cfg | 1350.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略配置 | NaN | Strategy | 13501.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 出口配置 | NaN | OutIntf | 13502.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 路由匹配 | NaN | 主要涉及匹配原则是否正确，元素包括：入接口、源地址、目的地址、服务\n | Match | 1351.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 入接口匹配 | NaN | IntfMatch | 13511.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 五元组匹配 | NaN | QuintupleMatch | 13512.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 应用匹配 | NaN | AppMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | 13513.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 路由转发 | NaN | 验证匹配以后转发是否正确，下一跳类型包括网关和出接口，同时覆盖权重的验证\n | Routing | 1352.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 网关转发 | NaN | GateWayFwd | 13521.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 出接口转发 | NaN | OutIntfFwd | 13522.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载分担 | NaN | LoadBalance | 13523.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | IPv6策略路由转发 |
| NaN | NaN | NaN | 管理维护 | NaN | 主要涉及DFX的功能，包含可靠性、性能、升级、HA、公共日志、Bypass等功能 | Mng | 1353.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 13531.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv6策略路由 | NaN | NaN | 策略路由，是一种比基于目标网络进行路由更加灵活的数据包路由转发机制。路由器将通过路由图决定如何对需要路由的数据包进行处理，路由图决定了一个数据包的下一跳转发路由器。 | IPV6StrategyRoute | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | 策略路由配置管理，包括策略相关的所有接口的配置\n包括路由接口和优先级调整接口的增删改查，以及批量查询和删除接口 | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略配置 | NaN | Strategy | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 出口配置 | NaN | OutIntf | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 路由匹配 | NaN | 主要涉及匹配原则是否正确，元素包括：入接口、源地址、目的地址、服务\n | Match | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 入接口匹配 | NaN | IntfMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 五元组匹配 | NaN | QuintupleMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 应用匹配 | NaN | AppMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 路由转发 | NaN | 验证匹配以后转发是否正确，下一跳类型包括网关和出接口，同时覆盖权重的验证\n | Routing | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 网关转发 | NaN | GateWayFwd | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 出接口转发 | NaN | OutIntfFwd | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载分担 | NaN | LoadBalance | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | IPv6策略路由转发 |
| NaN | NaN | NaN | 管理维护 | NaN | 主要涉及DFX的功能，包含可靠性、性能、升级、HA、公共日志、Bypass等功能 | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | ISP路由 | NaN | NaN | 一些用户会申请多条ISP线路进行流量负载均衡。在这种业务场景下，如果通过ISP 1的线路访问ISP 2的服务器，网速会降低。针对该问题，NGFW提供ISP路由功能，使不同ISP流量走专有路由，从而提高网络速度。 | ISP | 136.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | ISP信息管理，ISP信息导出 | Cfg | 1360.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ISPv4库配置 | NaN | ISPv4Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ISPv6库配置 | NaN | ISPv6Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ISP路由配置 | NaN | ISPRouteCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | ISPv4路由 | NaN | NaN | ISPv4Route | 1361.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由表维护 | NaN | ISPv4RouteTale | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | 包含等价路由、源进源出、业务转发、URPF等 | ISPv4Routing | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载均衡 | 包括源进源出 | ISPv4LB | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | ISPv6路由 | NaN | NaN | ISPv6Routing | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | ISP管理，ISP路由维护，路由转发 |
| NaN | NaN | NaN | NaN | 路由表维护 | NaN | ISPv6RouteTale | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | 包含等价路由、源进源出、业务转发、URPF等 | ISPv6Routing | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载均衡 | 包括源进源出 | ISPv6LB | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | OSPFv2 | NaN | NaN | OSPF（Open Shortest Path First）是IETF组织开发的一个基于链路状态的内部网关协议（Interior Gateway Protocol）。\n目前针对IPv4协议使用OSPF Version 2，针对IPv6协议使用OSPF Version 3。 | Ospfv2 | 137.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1370.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | OSPFv2配置 | NaN | Ospfv2Cfg | 13701.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 协议协商 | NaN | IPv4网络中运行的OSPF，包含协议交互和路由转发 | Protocol | 1371.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 状态协商 | NaN | Negotiate | 13711.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由计算 | NaN | Caculate | 13712.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由通告 | NaN | Inform | 13713.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | NaN | ServiceFwd | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Routing | 13714.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 13715.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | OSPFv3 | NaN | NaN | NaN | OSPFv3 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1372.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | OSPFv3配置 | NaN | OSPFv3Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 协议协商 | NaN | NaN | Protocol | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 状态协商 | NaN | Negotiate | 13721.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由计算 | NaN | Caculate | 13722.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由通告 | NaN | Inform | 13723.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | NaN | ServiceFwd | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Routing | 13724.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 13725.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | OSPF,源进源出 |
| NaN | NaN | RIP | NaN | NaN | RIP是Routing Information Protocol（路由信息协议）的简称。它是一种较为简单的内部网关协议IGP（Interior Gateway Protocol），主要应用于规模较小的网络中，例如校园网以及结构较简单的地区性网络。对于更为复杂的环境和大型网络，一般不使用RIP协议。\n | Rip | 138.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1380.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | RIP配置 | NaN | ripCfg | 13801.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 协商和转发 | NaN | RIP是一种基于距离矢量（Distance-Vector）算法的协议，它通过UDP报文进行路由信息的交换，使用的端口号为520。\nRIP使用跳数（Hop Count）来衡量到达目的地址的距离，称为度量值。在RIP中，缺省情况下，路由器到与它直接相连网络的跳数为0，通过一个路由器可达的网络的跳数为1，其余依此类推。也就是说，度量值等于从本网络到达目的网络间的路由器数量。为限制收敛时间，RIP规定度量值取0～15之间的整数，大于或等于16的跳数被定义为无穷大，即目的网络或主机不可达。由于这个限制，使得RIP不可能在大型网络中得到应用。 | RIP | 1381.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由维护 | NaN | RoutingTable | 13812.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Forward | 13813.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 13814.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | BGP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | BPG配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 协议协商 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 状态协商 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由计算 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由通告 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 服务协议 | NaN | NaN | NaN | 网络服务相关的动态协议 | ServiceProtocol | 14.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | DHCP | NaN | NaN | DHCP（动态主机配置协议）是一个局域网的网络协议。指的是由服务器控制一段IP地址范围，客户机登录服务器时就可以自动获得服务器分配的IP地址和子网掩码。 | Dhcp | 141.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Dhcpv4 | 1410.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DHCPV4配置 | NaN | v4Cfg | 14101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DHCPV6配置 | NaN | v6Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DHCPV4 | NaN | IPV4网络中运行的DHCP协议版本 | Dhcpv4 | 1411.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 需求新增五级目录DFX | NaN |
| NaN | NaN | NaN | NaN | DHCP服务 | 设备作为服务端向客户端提供地址分配等相关功能 | Service | 14111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DHCP中继 | NaN | Relay | 14112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DHCP客户端 | NaN | Client | 14113.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DHCPv6 | NaN | NaN | Dhcpv6 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DHCPv6服务 | NaN | Service | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DHCPV6中继 | NaN | Relay | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DHCPV6客户端 | NaN | Client | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | DNS | NaN | NaN | 域名系统（英文：Domain Name System，缩写：DNS）是互联网的一项服务。它作为将域名和IP地址相互映射的一个分布式数据库，能够使人更方便地访问互联网。\nIPv4网络中运行的DNS协议，包括：静态DNS、动态缓存、DNS透明代理和DNS服务器几个功能点 | Dns | 142.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态DNS配置 | NaN | StcDnsCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DNS服务器配置 | NaN | DnsServerCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 动态缓存操作 | NaN | CacheCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DDNS配置 | NaN | DDNSCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DNS服务 | NaN | 包括：静态DNS、动态缓存\n在防火墙上会存在DNS表项，在不存在表项时向服务器发起DNS请求，获取到域名解析后返回给客户端。 | Service | 1421.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态DNS | NaN | StaticAgent | 14211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 动态代理 | NaN | DynamicAgent | 14212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DNS中继 | NaN | DNS作为中继服务，直接透传客户端的DNS请求，不做缓存等操作 | Relay | 1422.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 透明代理 | NaN | Transparent | 14221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DNS客户端 | NaN | 防火墙作为DNS客户端向服务器发起DNS请求 | Client | 1423.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 客户端 | NaN | Client | 14231.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DDNS | NaN | NaN | DDNS | 1424.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DDNS客户端 | NaN | DDNSClient | 14241.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | MNG | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 14241.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | PPPoE | NaN | NaN | PPPoE | PPPoE | 143.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | 包括：静态DNS、动态缓存\n在防火墙上会存在DNS表项，在不存在表项时向服务器发起DNS请求，获取到域名解析后返回给客户端。 | Cfg | 1430.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口配置 | NaN | IntfCfg | 14301.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 协商和转发 | NaN | DNS作为中继服务，直接透传客户端的DNS请求，不做缓存等操作 | Protocol | 1431.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | PPPoE协商 | NaN | Negotiate | 14311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由转发 | NaN | Fwd | 14312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | VPN | NaN | NaN | NaN | NaN | vpn | 15.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPSecVpn | NaN | NaN | NaN | Ipsec | 151.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1510.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 基本配置 | NaN | BaseCfg | 15101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 安全提议 | NaN | SecProposal | 15102.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IKE协商 | NaN | NaN | IKE | 1511.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IKEv1协商 | NaN | IKEv1 | 15111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IKEv2协商 | NaN | IKEv2 | 15112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IPSec协商 | NaN | NaN | IPSecNegotiate | 1512.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 封装模式 | NaN | EncapMode | 15121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 安全协议 | NaN | SecProtocol | 15122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 数据传输 | NaN | DataFwd | 15123.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 1513.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 15131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 协议协商 | 认证方式 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IKE协商 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPSec协商 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 基础业务 | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 抗重放 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 典型场景 | NAT耦合 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载分担 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双机热备 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | SSLVpn | NaN | NaN | NaN | SSLVpn | 152.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1520.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 网关配置 | NaN | GateWay | 15201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 资源配置 | NaN | Resource | 15202.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | VPN管理 | NaN | NaN | VpnMng | 1521.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 门户网站 | NaN | PortalSiete | 15211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 用户管理 | NaN | UserMng | 15212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 客户端 | NaN | Client | 15213.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 数据转发 | NaN | NaN | DataFwd | 1522.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由控制 | NaN | RouteCtrl | 15221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 资源访问 | NaN | ResourceAccess | 15222.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IP隧道 | NaN | NaN | NaN | IPTnl | 153.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 1530.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 隧道配置 | NaN | Tnl | 15301.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 手工隧道 | NaN | NaN | ManualTnl | 1531.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 6in4隧道 | NaN | 6in4 | 15311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 4in6隧道 | NaN | 4in6 | 15312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | GRE隧道 | NaN | gre | 15313.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 自动隧道 | NaN | NaN | AutoTnl | 1532.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ISATAP隧道 | NaN | isatap | 15321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 6to4隧道 | NaN | 6to4 | 15322.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 6RD隧道 | NaN | 6rd | 15323.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DS-Lite隧道 | NaN | ds-lite | 15324.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 高可靠性 | NaN | NaN | NaN | NaN | 可靠性是降低网络中断时间、保证网络中业务质量，提升用户体验的一项技术。\n可靠性技术是实现高可靠性的一系列技术。它主要涉及到系统及硬件可靠性设计方法、软件可靠性设计方法、可靠性测试验证方法和IP网络可靠性设计。\n随着网络的快速普及和应用的日益深入，各种增值业务在网络上得到了广泛部署，网络带宽也以指数级增长，网络短时间的中断就可能影响大量业务，造成重大损失。\n作为业务承载主体的基础网络，其可靠性也因此成为日益关注的焦点。\n本文关注的是NE40E上实现的IP网络可靠性技术 | HiRel | 2.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 高可用 | NaN | NaN | NaN | 可用性（High Availability，简称HA）能够在通信线路或设备发生故障时提供备用方案，防止由于单个产品故障或链路故障导致网络中断，保证网络服务的连续性。实现HA功能需要部署两台同一型号的设备，并且选择同样的接口作为HA接口。两台设备之间通过HA接口直连，当一台设备不可用时，用户请求会被及时转发到另外一台设备上处理，网络通信不会中断。 | HA | 21.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | HA | NaN | NaN | 通过冗余备份等方式实现高可用 | HA | 211.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 2110.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | HA配置 | NaN | HACfg | 21101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | VRRP配置 | NaN | VrrpCfg | 21102.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 双机热备 | NaN | 1、创建、修改和删除高可用组功能（包括主备模式、主主模式，同步选项、抢占模式、通讯端口、监控端口、探测地址相关管理等）\n2、双机热备状态\n3、双机热备支持的场景 | Backup | 2111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 热备状态机 | NaN | Switch | 21111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 数据同步 | NaN | syn | 21112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 部署场景 | 可用组内设备间配置同步（包括设备所有的配置、以及监控配置、接口地址等）和状态同步（包括接口状态同步、接口状态探测） | secenario | 21113.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | VRRP | NaN | NaN | Vrrp | 2112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | VRRP状态机 | NaN | machine | 21121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | VIP管理 | 1、vip的ARP、虚MAC的使用等\n2、vrrp状态变化，虚拟IP的生成和删除 | vip | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由维护 | 1、直连路由和下一跳与虚拟IP同网段时的路由状态联动\n2、主备切换后vip变化，联动路由表的变化 | RouteMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 2113.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 21131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 链路探测 | NaN | NaN | NaN | LinkProbe | 212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 2120.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 链路探测配置 | NaN | LinkProbeCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 探测业务 | NaN | NaN | linkProbe | 2121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IP-Link | IP,tcp | IPLink | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IP-Link组 | NaN | IPLinkGroup | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 质量探测 | NaN | LinkQualityProbe | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | DFR |
| NaN | NaN | Bypass | NaN | NaN | NaN | Bypass | 213.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 2130.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 旁路配置 | NaN | bpCfg | 21301.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 硬件Bypass | NaN | NaN | HWBypass | 2131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | BP分组识别 | NaN | BPGroup | 21311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 二层Bypass | NaN | SwitchBP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口对Bypass | NaN | PairBP | 21311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 软件Bypass | NaN | NaN | SWBypass | 2132.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 数通Bypass | NaN | vppBypass | 21321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 安全Bypass | NaN | SnortBypass | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 可靠性,可服务性 |
| NaN | NaN | BFD | NaN | NaN | NaN | Bfd | 214.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 2140.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | OSPF配置 | NaN | ospfCfg | 21401.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | BFD管理 | NaN | NaN | BfdMng | 2141.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | BFD控制 | NaN | BfdCtrl | 21411.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 会话 | NaN | Session | 21412.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志 | NaN | Log | 21413.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | BFD4ALL | NaN | NaN | Bfd4All | 2142.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | BFD4OSPF | NaN | Bfd4Ospf | 21421.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 服务质量 | NaN | NaN | NaN | NaN | Qos | 22.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv4带宽管理 | NaN | NaN | 务质量QoS（Quality of Service）是针对各种业务的不同需求，为其提供端到端的服务质量保证。QoS不会增加网络带宽，它是有效利用现有网络资源的工具，允许不同的流量不平等的竞争网络资源，语音、视频和重要的数据应用在网络设备中可以优先得到服务。\n随着网络技术的飞速发展，互联网中的业务越来越多样化。除了传统的WWW、E-Mail、FTP应用外，用户还尝试在Internet上拓展新业务，比如IP电话、电子商务、多媒体游戏、远程教学、远程医疗、可视电话、电视会议、视频点播、在线电影等。企业用户也希望通过VPN技术，将分布在各地的分支机构连接起来，开展一些事务性应用，比如访问公司的数据库或通过Telnet管理远程设备。 | IPv4BwMng | 221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | 接口带宽、策略模板和策略应用的配置和管理 | Cfg | 2210.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口配置 | NaN | IntfBw | 22101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 通道配置 | NaN | Channel | 22102.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4策略配置 | NaN | IPv4Policy | 22103.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 流量策略 | NaN | 1、匹配接口策略可以进行接口Qos处理\n2、匹配通道的流量可以进行接口和通道的Qos处理\n3、匹配用户的流量可以进行用户、通道和接口对应的Qos功能处理 | FlowPolicy | 2211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | Match | 22111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 优先级管理 | NaN | Preference | 22112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略分析 | NaN | Analyze | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 流量限制 | NaN | 1、各种模式下的带宽限制\n2、各种模式下带宽保证和抢占 | car | 2212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 带宽保障 | NaN | cir | 22121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 带宽限制 | NaN | Pir | 22122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 总额限制 | NaN | TotalData | 22123.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 连接限制 | NaN | 基于通道和用户连接速率和连接数量的限制 | FlowLimit | 2213.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 并发连接限制 | NaN | ConcrrentFlows | 22131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 新建速率限制 | NaN | FlowRate | 22132.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 2214.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 22141.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv6带宽管理 | NaN | NaN | NaN | IPv6BwMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6策略配置 | NaN | IPv6Policy | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 流量策略 | NaN | NaN | FlowPolicy | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | Match | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | Preference | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略分析 | NaN | Analyze | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 流量限制 | NaN | NaN | car | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 带宽保障 | NaN | cir | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 带宽限制 | NaN | Pir | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 总额限制 | NaN | TotalData | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 连接限制 | NaN | NaN | FlowLimit | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 并发连接限制 | NaN | ConcrrentFlows | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 新建速率限制 | NaN | FlowRate | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 安全特性 | NaN | NaN | NaN | NaN | NaN | Security | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 网络层安全 | NaN | NaN | NaN | NaN | NetSec | 31.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 黑白名单 | NaN | NaN | NaN | WhiteBlack | 311.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3110.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 黑名单配置 | NaN | BlackCfg | 31101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 白名单配置 | NaN | WhiteCfg | 31102.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 白名单 | NaN | 白名单配置、命中白名单放行 | WhiteList | 3111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 白名单策略 | NaN | WhitePolicy | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 黑名单 | NaN | 黑名单配置、黑名单阻断、启停、黑名单自动过期，查看黑名单历史记录查看 | BlackList | 3112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 黑名单策略 | NaN | BlackPolicy | 31121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 黑名单记录 | NaN | BlackRecord | 31122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 域名黑名单 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 黑白名单日志和可靠性 | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 黑白名单日志、黑白名单导入导出 |
| NaN | NaN | NaN | NaN | 导入导出 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 功能联动 | NaN | Linkage | 3113.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPMac绑定 | NaN | NaN | NaN | IPMacBind | 312.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3120.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPMac配置 | NaN | IPMacCfg | 31201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 跨三层IPMac配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IPMac策略 | NaN | NaN | IPMacPolicy | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 严格绑定 | 限制除IP和MAC完全匹配和完全不匹配的包 | Strict | 3121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 非严格绑定 | 限制IP相同、MAC不同的包 | Loose | 3122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 四级目录非严格绑定，两个五级目录耦合，可维护性 |
| NaN | NaN | NaN | 跨三层IPMac | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNMP服务器 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3123.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 频繁增删、策略冲突检测、绑定数量 | DFX | 31231.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NAT44 | NaN | NaN | NaN | Nat44 | 313.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地址池配置 | NaN | PoolCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNAT配置 | NaN | SnatCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DNAT配置 | NaN | DnatCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态NAT配置 | NaN | StaticNatCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | NAT |
| NaN | NaN | NaN | NaN | 服务器负载配置 | NaN | LoadBCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | SNAT | NaN | NaN | Snat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | PolicMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 转换方式 | NaN | Translation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNAT邻居 | 地址池、出接口相关的ARP处理 | SnatArp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DNAT | NaN | NaN | Dnat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | PolicMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 转换方式 | NaN | Translation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DNAT邻居 | NaN | DnatArp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双向NAT | NaN | BiNat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 服务器负载 | NaN | NaN | SrvLoadB | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | PolicMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 转换方式 | DNAT44转换方式和DNAT44负载 | Translation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载邻居 | NaN | LoadBArp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双向NAT | NaN | BiNat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 静态NAT | NaN | NaN | StaticNat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | PolicMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT优先级 | SNAT、DNAT、静态NAT均匹配是的优先级 | NatPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略分析 | NaN | Analyze | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双机热备 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NAT66 | NaN | NaN | NaN | Nat66 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3130.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地址池配置 | NaN | poolCfg | 31301.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNAT配置 | NaN | SnatCfg | 31302.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DNAT配置 | NaN | DnatCfg | 31303.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 静态NAT配置 | NaN | StaticNatCfg | 31304.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 服务器负载配置 | NaN | LoadBCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | SNAT | NaN | NaN | Snat | 3131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | 五元组匹配、地址转换、出接口识别 | PolicMatch | 31313.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 转换方式 | NaN | Translation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNAT邻居 | 五元组匹配、地址转换 | SnatNd | 31314.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | DNAT | NaN | NaN | Dnat | 3132.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | 多地址负载、协议报文识别 | PolicMatch | 31321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 转换方式 | DNAT转换方式和负载分担 | Translation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | 四元组匹配、地址端口转换、 | PolicyPriority | 31322.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DNAT邻居 | 四元组匹配、地址端口转换 | DnatArp | 31323.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双向NAT | NaN | BiNat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 服务器负载 | NaN | NaN | Dnat | 3132.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | 多地址负载、协议报文识别 | PolicMatch | 31321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 转换方式 | DNAT转换方式和负载分担 | Translation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | 四元组匹配、地址端口转换、 | PolicyPriority | 31322.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 负载邻居 | 四元组匹配、地址端口转换 | LoadBArp | 31323.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双向NAT | NaN | BiNat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 静态NAT | NaN | NaN | StaticNat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | PolicMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3134.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT优先级 | NAT66内部优先级，NAT66与NAT44和NAT64之间的优先级 | NatPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 频繁增删、模块启停、策略数量 | DFX | 31341.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略分析 | NaN | Analyze | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双机热备 | NaN | Analyze | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 跨协议NAT | NaN | NaN | NaN | ProtocolNat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT64配置 | NaN | Nat64Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT46配置 | NaN | Nat46Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | C01SPC200 | NaN |
| NaN | NaN | NaN | NAT64 | NaN | NaN | Nat64 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | PolicMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT64邻居 | NaN | Nat64Neighbor | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NAT46 | NaN | NaN | Nat46 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | C01SPC200 | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | PolicMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | C01SPC200 | NaN |
| NaN | NaN | NaN | NaN | 策略优先级 | NaN | PolicyPriority | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | C01SPC200 | NaN |
| NaN | NaN | NaN | NaN | NAT46邻居 | NaN | Nat46Neighbor | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | C01SPC200 | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | Dfx | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 双机热备 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | ASPF | NaN | NaN | NaN | Aspf | 314.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3140.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ASPF配置 | 配置协议主端口、开关 | AspfCfg | 31401.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务转发 | NaN | NaN | Fwd | 3141.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | FTP | 主动模式、被动模式 | Ftp | 31411.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | H323 | 直连模式、网守模式中的声音、桌面、视屏等分享 | H323 | 31412.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SIP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | C01SPC200 | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3142.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 多主端口模式下的动态端口开放、启停后的动态端口恢复与释放 | Rel | 31421.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv4控制策略 | NaN | NaN | NaN | IPv4Acl | 315.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | 待删除 | 安全策略 |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4策略配置 | NaN | IPv4AclCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4策略分析配置 | NaN | IPv4AclAnaCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4策略组配置 | NaN | IPv4AclGroupCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 控制策略 | NaN | NaN | AclCtrl | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 五元组匹配 | SIP、DIP、协议、SPORT和DPORT匹配 | QuintupleMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 多元匹配 | 除SIP、DIP、协议、SPORT和DPORT之外的属性匹配 | MultitupleMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略动作 | 允许、拒绝、防火墙日志、安全引擎耦合 | PolicyAction | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 命中管理 | NaN | HitMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4策略分析 | NaN | IPv4AclAna | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 可靠性、导入导出 | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | IPv6控制策略 | NaN | NaN | NaN | IPv6Acl | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6策略配置 | NaN | IPv6AclCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6策略分析配置 | NaN | IPv6AclAnaCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6策略组配置 | NaN | IPv6AclGroupCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 控制策略 | NaN | NaN | AclCtrl | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 五元组匹配 | SIP、DIP、协议、SPORT和DPORT匹配 | QuintupleMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 多元匹配 | 除SIP、DIP、协议、SPORT和DPORT之外的属性匹配 | MultitupleMatch | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略动作 | 允许、拒绝、防火墙日志、安全引擎耦合，策略优先级 | PolicyAction | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 命中管理 | NaN | HitMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6策略分析 | NaN | IPv4AclAna | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | Ddos | NaN | NaN | NaN | Ddos | 316.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3160.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DDos防护配置 | NaN | DdosCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DDos防护模板 | NaN | DdosTempCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 单包防护配置 | NaN | PktDefCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 抗DDos | NaN | NaN | AntiDDos | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 攻击检测 | NaN | AttackInspect | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 攻击响应 | NaN | AttackReply | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 单包防护 | NaN | NaN | PktDefense | 3161.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 畸形报文攻击 | NaN | MalformedPkt | 3162.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 扫描报文攻击 | NaN | ScanPkt | 3163.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 3164.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 旁路检测 | NaN | NaN | NaN | BypassDetection | 318.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3180.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 旁路配置 | NaN | BPCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 端口镜像配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 旁路检测 | NaN | NaN | Detection | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 端口镜像 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 流量检测 | NaN | FlowDetection | 3181.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 本地控制策略 | NaN | NaN | NaN | AppSec | 32.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4本地策略配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6本地策略配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IPv4本地策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略动作 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 命中管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IPv6本地策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略动作 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 命中管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 应用层安全 | NaN | NaN | NaN | NaN | AppSec | 32.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 应用识别 | NaN | NaN | NaN | AppIdentify | 321.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfd | 3210.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 应用配置 | 预定义自定义应用配置 | App | 32101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 标签配置 | 标签配置、增删改查 | Mark | 32102.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则配置 | 规则检测文件生成 | Rule | 32103.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 应用规则 | NaN | NaN | AppRule | 3213.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | TCP&UDP | tcp和udp类型应用 | TcpUdp | 32131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | HTTP | http应用，url/Contentype | Http | 32132.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SSL | NaN | ssl | 32133.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SIP | NaN | sip | 32134.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | RTMP | NaN | Rtmp | 32135.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 预定义应用 | NaN | PredefinedApp | 32136.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 耦合 | NaN | NaN | 32137.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 耦合 |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3214.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 多应用识别能力及效率，包含升级、HA、证书授权、公共日志等功能，导入导出 | DFX | 32141.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 导入导出 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 内容过滤 | NaN | NaN | NaN | ContentFilter | 322.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3220.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 关键字配置 | NaN | KeyWordCfg | 32201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 内容过滤配置 | NaN | ContetCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 过滤策略 | NaN | NaN | Policy | 3221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 配置文件 | 基础配置、过滤项目配置、过滤协议配置 | File | 32211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 过滤协议 | smtp/pop/imap/http/ftp/telnet | ProtocolFilter | 32212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 访问控制 | 告警、阻断、ACL引用 | AccessCtrl | 32213.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3222.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 告警阻断日志 | DFX | 32221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | URL过滤 | NaN | NaN | NaN | UrlFilter | 323.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3230.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | URL配置 | NaN | UrlCfg | 32301.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | URL对象 | NaN | UrlObj | 32302.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 过滤策略 | NaN | NaN | Policy | 3231.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | URL防护 | 恶意url阻断 | UrlPro | 32311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 访问控制 | 告警、阻断、ACL引用 | AccessCtrl | 32312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3232.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 告警阻断日志 | DFX | 32321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 文件过滤 | NaN | NaN | NaN | FileFilter | 324.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3240.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 文件过滤配置 | NaN | FileFilterCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则配置 | NaN | RuleCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | MD5配置 | NaN | Md5cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 过滤策略 | NaN | NaN | Policy | 3241.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 过滤类型 | smtp/pop/imap/http/ftp | FilterType | 32411.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 访问控制 | 放行、阻断、告警、ACL引用 | AccessCtrl | 32414.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 过滤大小 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 压缩层级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3242.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 大文件识别、解压缩效率 | DFX | 32421.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | WEB防护 | NaN | NaN | NaN | WebProtect | 325.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3250.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | Web过滤配置 | NaN | Filter | 32501.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | Web防护配置 | NaN | Policy | 32502.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则库配置 | NaN | Rule | 32503.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 规则库配置、规则匹配、访问频率控制 |
| NaN | NaN | NaN | 过滤策略 | NaN | NaN | Policy | 3251.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | WAF规则 | NaN | WafRule | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 配置管理 | web过滤配置文件、检测字段、匹配方式 | CfgMng | 32511.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 访问控制 | 告警、阻断、ACL引用 | AccessCtrl | 32512.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3252.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 多匹配项识别、识别效率 | DFX | 32521.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 防病毒 | NaN | NaN | NaN | AntiVirus | 326.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3260.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 协议配置 | NaN | Protocol | 32601.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 文件配置 | NaN | File | 32602.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 病毒白名单 | NaN | WhiteList | 32603.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 扫描模式 | NaN | NaN | ScanMode | 3261.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 快速扫描 | 扫描可执行文件 | RapidScan | 32611.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 自定义扫描 | 自定义文件类型扫描 | CustomScan | 32612.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 全文扫描 | 所有文件扫描 | FullScan | 32613.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 病毒检测 | NaN | NaN | VirusDetect | 3262.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 病毒类型 | NaN | VirusType | 32621.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 支持协议 | smtp/pop/imap/http/ftp | Portocol | 32622.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 压缩文件 | 大小限制/解压层数限制/启停 | CompressFile | 32623.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 病毒白名单 | 防病毒白名单例外 | WhiteVirus | 32624.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3263.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 扫描速度、大文件扫描效率、解压缩效率 | DFX | 32631.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 入侵防御 | NaN | NaN | 【定义】可识别潜在的威胁并迅速地做出应对的网络安全防范的系统或体系\n【范围】涉及防护规则、配置文件、入侵联动防护和耦合、DFX等功能。 | IPS | 327.0 | NaN | NaN | NaN | NaN | NaN | NaN | 2.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3270.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 配置文件配置 | NaN | RuleCfg | 32711.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则配置 | NaN | RuleFeature | 32713.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 规则库 | NaN | 主要覆盖防护规则的验证，包含预定义和自定义规则 | Rules | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则特征 | NaN | RuleFeature | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置文件 | NaN | 主要覆盖配置文件的验证，涉及基本配置、配置列表和条件之前相互关系等。 | CfgFile | 3272.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 条件列表 | NaN | CondiList | 32722.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 条件关系 | NaN | CondiRelat | 32723.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 入侵检测 | NaN | IPS与其他功能的耦合以及入侵基本大类的验证。 | IpsDetect | 3273.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 控制策略引用 | NaN | PolicyRef | 32731.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则检测 | NaN | RuleDetect | 32732.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志降噪 | NaN | LogNoise | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | IPS中DFX非功能需求部分的验证 | Mng | 3274.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 32741.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | SSL卸载 | NaN | NaN | NaN | SSLUninstall | 328.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3280.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 证书配置 | NaN | CA | 32801.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 解密规则配置 | NaN | Decrypt | 32802.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 引用配置 | NaN | Ref | 32803.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 双向代理 | NaN | NaN | BiAgency | 3281.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | Web双向代理 | NaN | Web | 32811.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 邮件双向代理 | NaN | Email | 32812.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 3283.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 328131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 性能，权限控制 |
| NaN | NaN | 资产管理 | NaN | NaN | NaN | AssertManage | 329.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3291.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 资产配置 | NaN | AssertCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 扫描配置 | NaN | ScanCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 标签配置 | NaN | MarkCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 资产管理 | NaN | NaN | AssertMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 资产发现 | NaN | AssertDis | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 信息管理 | NaN | InfoMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 威胁管理 | NaN | NaN | ThreatMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 漏洞管理 | NaN | Vulnerability | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 弱密码管理 | NaN | WeakPwd | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 信息统计 | NaN | NaN | InfoStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 资产统计 | NaN | AssertSta | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 威胁统计 | NaN | ThreatSta | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 防破解 | NaN | NaN | NaN | AntiCracking | 329.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 防暴力破解配置 | NaN | CrackCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 弱密码配置 | NaN | WeakPwdCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 弱密码 | NaN | NaN | WeakPwd | 3202.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 协议匹配 | NaN | Protocol | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 弱密码规格 | NaN | WeakPwd | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 防暴力破解 | NaN | NaN | AFCracking | 3203.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 黑名单联动 | NaN | BlackLlink | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 服务规则匹配 | NaN | AFCracking | 3203.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | DNS检测 | NaN | NaN | NaN | DNSDetect | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | CFG | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DGA配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DNS过滤配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 全局配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 检测类型 | NaN | NaN | DetectType | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DGA | NaN | DGA | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DNS过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 应用过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 应用过滤配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 过滤规则 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 规则匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 访问控制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 安全分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志分析配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 报表查询配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 日志分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 基础分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 联动分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 分析报表 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 联动 | NaN | NaN | NaN | NaN | Cooperation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 应用层安全目录下的EDR |
| NaN | NaN | EDR | NaN | NaN | NaN | EDR | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 整体挪动了二级目录 | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接入配置 | NaN | AccessCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 全局配置 | NaN | GlobalCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 推广策略配置 | NaN | PolicyCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 联动 | NaN | NaN | Cooperation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接入EDR平台 | NaN | EdrServer | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | EDR平台推送 | NaN | EdrPush | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | EDR客户端 | NaN | EdrClient | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 应用层安全目录下的威胁情报 |
| NaN | NaN | UES | NaN | NaN | NaN | UES | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接入配置 | NaN | AccessCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 全局配置 | NaN | GlobalCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 推广策略配置 | NaN | PolicyCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 联动 | NaN | NaN | Cooperation | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接入UES平台 | NaN | UesServer | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | UES平台推送 | NaN | UesPush | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | UES客户端 | NaN | UesClient | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 威胁情报 | NaN | NaN | NaN | ThreatIntel | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 整体挪动了二级目录 | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 情报订阅 | NaN | IntelSubCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 热点查询 | NaN | TrendQueryCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 情报功能 | NaN | NaN | IntelFunc | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 全网威胁情报 | NaN | GlobalThreatIntel | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 威胁事件分析 | NaN | ThreatAna | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 热点威胁情报 | NaN | TrendThreatIntel | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 对象 | NaN | NaN | NaN | NaN | Object | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 对象管理 | NaN | NaN | NaN | ObjMng | 331.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 3310.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地址配置 | NaN | IpAddr | 33101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地址组配置 | NaN | IpGroup | 33102.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 服务配置 | NaN | Service | 33103.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 服务组配置 | NaN | SrvGroup | 33104.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 时间对象配置 | NaN | Time | 33105.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | MAC地址配置 | NaN | MAC | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 域名配置 | NaN | Domain | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6地址配置 | NaN | IPv6Addr | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6地址组配置 | NaN | IPv6AddrGrp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 证书配置 | NaN | Certify | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地区配置 | NaN | Area | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 地址对象 | NaN | NaN | Addr | 3311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPV4地址 | 预定义地址、自定义IPv4地址 | Ipv4Addr | 33111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPV4地址组 | 地址组管理预定义和自定义IPv4地址 | Ipv4AddrGrp | 33112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPV6地址 | 预定义地址、自定义IPv6地址 | Ipv6Addr | 33113.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPV6地址组 | 地址组管理预定义和自定义IPv6地址 | Ipv4AddrGrp | 33114.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | MAC地址 | NaN | MacAddr | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 域名地址 | NaN | Domain | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 服务对象 | NaN | NaN | Srv | 3312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 预定义服务 | 预定义服务列表、ACL引用 | PreSrv | 33121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 自定义服务 | 使用协议号、端口自定义服务，ACL引用 | CusSrv | 33122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 服务组 | 管理预定义和自定义服务、ACL引用 | SrvGroup | 33123.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 关键字对象 | NaN | NaN | NaN | 3313.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 关键字对象 | 对象的增删改查，内容过滤和web过滤的引用 | NaN | 33131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 时间对象 | NaN | NaN | Time | 3314.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 时间控制 | 名称、类型、时间段配置，保证时间计划能正常启动 | TimeObj | 33141.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 证书对象 | NaN | NaN | Certificate | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 本地证书对象 | NaN | LocalCert | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | CA证书管理 | NaN | CaCert | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | CRL管理 | NaN | CrlCert | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 应用对象 | NaN | NaN | APP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 预定义应用 | NaN | PreApp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 自定义应用 | NaN | CusAPP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 文件对象 | NaN | NaN | File | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 文件类型 | NaN | FileType | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 文件类型组 | NaN | FileTypeGrp | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 导入导出 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 用户管理 | NaN | NaN | 对通过防火墙进行上网操作的用户的管理 | UsrCtrl | 332.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 用户配置管理 | NaN | 对用户相关信息数据进行增删改查等操作 | UsrCfg | 3320.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 用户 | NaN | User | 33201.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 用户组 | NaN | UsrGroup | 33202.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPMac绑定 | NaN | IPMac | 33203.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 认证域 | NaN | Domain | 33204.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 用户导入 | NaN | UsrImport | 33205.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 角色管理 | NaN | RoleMng | 33206.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 在线用户 | NaN | OnlineUsr | 33207.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 认证配置管理 | NaN | 对认证服务器、认证配置、认证策略进行增删改查操作 | AuthCfg | 3321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 认证策略 | NaN | Strategy | 33211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 认证服务器 | NaN | Server | 33212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 认证配置 | NaN | AuthCfg | 33213.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 多因子配置 | NaN | MulFactor | 33214.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 用户认证 | NaN | NaN | UsrAuth | 3322.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 认证类型 | NaN | AuthType | 33221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 认证策略 | NaN | AuthStrategy | 33222.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 在线用户 | NaN | OnlineUsr | 33223.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 用户导入 | NaN | UsrImport | 33224.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 认证服务器 | NaN | AuthServer | 33225.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 五级目录管理维护 |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 33226.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 管理维护 | NaN | NaN | NaN | NaN | NaN | Mng | 4.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | Cfg | 41.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 接入管理 | NaN | NaN | 【特性定义】多种接入方式的功能验证，主要涉及接口相互联系、接入后配置下发等。 | Access | 411.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4110.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接入管理配置 | NaN | AccessCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接入方式 | NaN | NaN | AccSrv | 4111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | HTTPS接入 | 通过管理口和业务口接入HTTPS | Https | 41111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SSH接入 | 管理口、业务口、串口SSH接入 | SSH | 41112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | ICMP功能 | PING管理口和业务口 | Ping | 41113.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 隧道接入 | 通过IPSec、SSLVPN、IP隧道方式接入 | Tunnel | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 串口管理，挪到串口控制 |
| NaN | NaN | NaN | NaN | Telnet管理 | 当前不支持 | Telnet | 41114.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | 待删除 | 四级目录 接入功能，管理业务分离 |
| NaN | NaN | NaN | 接入控制 | NaN | NaN | AccCtrl | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 协议控制 | HTTP协议控制（包括是否允许、协议端口）、SSH控制、PING控制，包括管理口和业务口。 | Protocol | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地址控制 | IP地址和MAC地址控制，包括IPv6和IPv4 | Addr | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 串口控制 | 串口接入参数控制 | Console | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | CLI服务 | 管理口、业务口、串口、SSH、webCLI | Cli | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 升级、配置恢复、可靠性等 | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理业务分离 | NaN | NaN | Isolate | 4112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 启动恢复 | NaN | NaN | NaN | Recover | 412.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4120.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 备份配置 | NaN | BackCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置维护 | NaN | NaN | CfgMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 配置备份 | NaN | CfgBack | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 配置恢复 | NaN | CfgRecover | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 设备管理 | NaN | NaN | NaN | NaN | DeviceMng | 42.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 系统管理 | NaN | NaN | 【特性定义】NGFW系统管理公共部分，涉及系统信息、服务、诊断工具、实时监控以及时间管理等等。 | SysMng | 421.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4210.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 系统信息配置 | NaN | devInfoCfg | 42101.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 实时监控配置 | NaN | RTMonCfg | 42102.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 告警配置 | NaN | AlarmCfg | 42103.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 系统时间配置 | NaN | TimeCfg | 42104.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 系统信息 | NaN | NaN | SysInfo | 4211.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备信息 | NaN | DevInfo | 42111.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 授权信息 | NaN | AuthInfo | 42112.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 系统服务 | NaN | NaN | SysSrv | 4212.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 系统重启 | NaN | reboot | 42121.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 引擎重启 | NaN | engineReboot | 42122.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 实时监控 | NaN | NaN | RTMon | 4213.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 系统状态 | NaN | SysStatus | 42131.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 并发数 | NaN | ConCurrent | 42132.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 流量监控 | 接口pps、丢包、错包 | FlowMon | 42133.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 告警 | NaN | NaN | Alarm | 4214.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 事件告警 | NaN | AlarmEvent | 42141.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 时间管理 | NaN | NaN | TIme | 4215.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 系统时间 | NaN | SysTime | 42151.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NTP | NaN | NTP | 42152.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 诊断工具 | NaN | NaN | NaN | DiagTool | 422.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4220.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 网络诊断配置 | NaN | NetDiagCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 抓包工具配置 | 配置用例 | CapToolCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 网络诊断 | NaN | NaN | NetDiag | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | Ping工具 | NaN | Ping | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | TraceRoute工具 | NaN | Tracert | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | Http(s)工具 | NaN | Https | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 抓包工具 | NaN | NaN | Captue | 4221.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 抓包管理 | NaN | CapMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 抓包文件管理 | NaN | File | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 管理员管理 | NaN | NaN | 对防火墙设备的各类管理员进行管理 | AdminMng | 423.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | 对管理员相关数据进行增删改查等操作 | Cfg | 4230.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 管理员配置 | NaN | Admin | 42301.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 权限配置 | NaN | privilege | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 在线用户查询 | 登录尝试次数限制的用例放到登录里面，这里只放在线用户查询用例 | OnlieUser | 42302.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 普通模式 | NaN | NaN | NormalMode | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 登录控制 | 1、内置账户和自定义账户的登录\n2、最大尝试次数，修改密码，密码过期，不操作自动登出（可配）\n3、在线用户数\n4、管理员IP限制 | LoginMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 权限控制 | 角色的默认权限和用户的定制权限（包含内置账户权限和自定义账户权限）系统管理员修改其他系统管理员的权限 | privMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 三权模式 | NaN | NaN | SepMode | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 模式管理 | 1、普通模式账户冻结、新增内置账户。回切处理 | ModeMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 系统管理员管理 | 1、包含账户、子账户、登录和权限、日志 | SysAdmin | 4231.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 审计员管理 | 1、包含账户、子账户、登录和权限、日志 | Audit | 42311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 安全员管理 | 1、包含账户、子账户、登录和权限、日志 | Security | 42312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 虚拟系统 | NaN | NaN | NaN | VirtualSys | 424.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4240.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 虚拟系统配置 | NaN | VirtualSysCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 系统管理 | NaN | NaN | SysMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 管理员管理 | 虚拟系统管理员管理内置用户和自定义用户，总览页面 | Admin | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 网络管理 | NaN | NaN | NetMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接口管理 | NaN | Intf | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 路由管理 | NaN | route | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 邻居管理 | NaN | Neighbor | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 策略管理 | NaN | NaN | Policy | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 对象管理 | NaN | Obj | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 控制策略管理 | NaN | Acl | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT策略管理 | NaN | nat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 统计监控 | NaN | StaMon | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志中心 | NaN | LogCenter | 4241.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 升级 | NaN | NaN | 【特性定义】主要涉及系统升级的功能，包括镜像、软件和特性库的升级、回滚功能等。 | Upgrade | 425.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4250.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 升级配置 | NaN | upgradeCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 升级 | NaN | NaN | Upgrade | 4251.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 软件全量升级 | NaN | FullUP | 42512.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 特征库升级 | NaN | FeatureLibUP | 42513.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 增量升级 | NaN | Path | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 回滚 | NaN | NaN | RollBack | 4252.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 软件回滚 | NaN | swback | 42522.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 特征库回滚 | NaN | libback | 42523.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 恢复出厂 | NaN | FacReset | 42524.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 增量包回滚 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 备份同步 | NaN | NaN | backUp | 4253.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 文件备份 | NaN | FileBack | 42531.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | SNMP | NaN | NaN | 【特性定义】SNMP网管协议方式的监控和管理，主要覆盖V1、V2和V3的基本功能。 | SNMP | 426.0 | NaN | NaN | NaN | NaN | NaN | NaN | 3.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4260.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNMP配置 | NaN | snmpCfg | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | SNMP管理 | NaN | NaN | SNMPMng | 4261.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 版本管理 | SNMP状态、SNMP版本切换 | version | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNMPv1v2 | 1、v1和v2基于团体名进行访问控制\n2、v1支持6个错误码，v2支持16个错误码\n3、v1不支持inform，v2支持inform\n4、v1和v2均支持get、getnext，getbulk、trap\n5、set根据版本规格视是否支持 | Snmpv1v2 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | SNMPv3 | 1、基于用户和用户组进行访问控制，加密认证\n2、v3支持get、getnext，getbulk、trap、iinform\n3、set根据版本规格视是否支持 | SNMPv3 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | MIB管理 | NaN | NaN | MIBMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 公有MIB | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 私有MIB | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 中电信量子MIB | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 4262.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 授权管理 | NaN | NaN | NaN | AuthMng | 427.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4271.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | license配置 | NaN | LicenseCfg | 42711.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | License管理 | NaN | NaN | LicenseMng | 4272.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | license生成 | NaN | lcsGenerate | 42721.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 证书导入导出 | NaN | certImOutPort | 42722.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 证书授权 | NaN | CertAuth | 42723.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 集中授权 | NaN | CentrAuth | 42724.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 证书服务器 | NaN | CertServer | 42725.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 会话管理 | NaN | NaN | NaN | Session | 429.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4290.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 会话配置 | NaN | SenssionCfg | 42901.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 业务处理 | NaN | NaN | Service | 4291.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 会话控制 | NaN | SessionCtl | 42911.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 会话监控 | NaN | SessionMon | 42912.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 4292.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 42921.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 监控统计 | NaN | NaN | NaN | NaN | MonSta | 43.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 流量统计 | NaN | NaN | 对设备流量的统计展示和对相应报表数据进行统计和展示\n1、流量统计是VPP进行统计后发送到Vpp-agent在写入influxdb\n2、流量统计只会对形成会话的报文进行流量统计，不会对未形成会话的报文（非IP报文）进行流量统计\n3、对于长会话的流量统计存在滞后 | Statistics | 431.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4310.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 流量监控配置 | NaN | TrafficStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 健康统计配置 | NaN | HealthStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 实时统计 | NaN | NaN | RTStatistic | 4311.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 流量统计 | NaN | TrafficStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 健康统计 | NaN | HealthStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 历史统计 | NaN | NaN | HisStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 流量统计 | NaN | TrafficStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 健康统计 | NaN | HealthStatistic | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 流量日志 | NaN | NaN | TrafficLog | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志清理 | NaN | LogClear | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 数据归并 | NaN | LogMerge | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 进程管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | 4312.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 报表中心 | NaN | NaN | NaN | ReportCenter | 432.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | cfg | 4320.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 报表模版配置 | NaN | ReportModel | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 报表任务配置 | NaN | ReportTask | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 报表管理 | NaN | 对报表的模板进行增删改查等配置操作 | ReportMng | 4321.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 报表生成 | 按照报表模板和报表任务生成报表（报表名称和内容） | ReportGenerate | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 报表管理 | 报表管理 | FormMng | 4322.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 查看历史报表 | DFX | 4323.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 日志中心 | NaN | NaN | 【特性定义】多种日志记录的公共功能，涉及系统、操作和防火墙日志的产品、记录是否正确以及查询是否正确等，安全日志中日志记录是否正确在特性中覆盖。 | LogCenter | 433.0 | NaN | NaN | NaN | NaN | NaN | NaN | 1.0 | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | Cfg | 4330.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志服务器配置 | NaN | LogSever | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志过滤配置 | NaN | LogFilter | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志备份配置 | NaN | LogBackup | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志归并配置 | NaN | LogMerge | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 调试日志配置 | NaN | DebugLog | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 信息收集配置 | NaN | InfoGather | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 异常信息导出配置 | NaN | ExportAbInfo | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 防火墙日志管理配置 | NaN | FWLogMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 日志管理 | NaN | NaN | LogMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 防火墙日志管理 | 日志查询、搜索、清除，包括系统日志、操作日志、安全日志、控制策略阻断日志。具体日志的产生的正确性由特性保证 | FWLogMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志归并 | NaN | LogMerge | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志清理 | 日志达到规格是，清除日志的20% | LogClear | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志备份 | NaN | LogBackup | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志导入导出 | NaN | LogImExport | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 日志服务器 | NaN | NaN | LogServer | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志外发 | 日志服务器连接，外发方式 | LogSender | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 外发过滤 | NaN | LogFilter | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志外发格式 | NaN | LogFormat | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 设备日志管理 | NaN | NaN | DeviceLogMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 调试日志管理 | 调试日志开关，调试日志轮转，进程日志管理，进程die日志 | DebugLogMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 信息收集 | 信息收集？信息收集、异常信息导出 | InfoGather | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | Mng | 4331.0 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 日志进程管理 | 日志进程守护dbtask,influxd,rsyslogd资源占用 | ProcessMng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | API | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | OpenAPI | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 对象接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4地址对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6地址对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4地址组对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6地址组对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地区对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 服务对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 服务组对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 时间对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 域名对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 策略接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4访问控制策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv4访问控制策略组 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6访问控制策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IPv6访问控制策略组 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 黑名单策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 白名单策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT44源NAT策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT44目的NAT策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT44静态NAT策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NAT44地址池 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 科信接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NP03网络访问控制服务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NP12网络入侵防御服务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NR01网络攻击抑制服务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | AI应用 | NaN | NaN | NR03共计诱捕服务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | AI应用平台 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | APP平台配置 | 对平台进行新增、删除、修改、查询等配置操作 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | APP配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 平台管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 磁盘管理 | 磁盘的检测和挂载、磁盘的启动条件、磁盘的状态查询和日志记录\n磁盘对APP的影响 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 内存管理 | OOM | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 平台服务管理 | 1、Docker系统管理：包括docker进程、docker服务器连接。。。。\n2、一机一策平台的启动条件\n | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 应用管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | APP管理 | 1、APP安装：安装、卸载和升级\n2、APP运维：启动、停止。开机自启动、开机手动启动\n3、APP健康检查与恢复、APP状态查询、APP服务代理\n4、APP日志记录等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 资源管理 | 动态菜单管理：动态菜单的注册与注销、固定菜单的API读写\nAPP之间数据互访：\n   rest接口的读写\n   日志的读写\n   公网权限（预留）\n | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | APP授权 | 1、验证可以按照单个APP进行授权，有免费授权、永久授权、到期续费\n2、内部需求、测试许可和正式许可是否有差异 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | 1、可靠性、稳定性和容错性\n2、与HA、启动恢复、基础系统、管理员管理、升级、授权、日志中心（系统日志和操作日志）、CLI、WebUI和系统管理的耦合 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 专项测试 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 应用场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 出口网关场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 出口网关单机多链路场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 出口网关双机主备场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 出口网关双机主备动态路由场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 出口网关双机主主动态路由场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 出口网关IP协议转换场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 混合部署场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 混合部署单机场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 混合部署主备场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 混合部署主主场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 隧道场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IPSec隧道场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IP隧道场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | SSLVPN场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 接口对场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接口对单机场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 接口对双机场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 云场景 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 天池云 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 系统可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 安全引擎可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 数通引擎可靠性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 可维可测 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 升级专项 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 集中管控 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 监控大屏配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备纳管配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备运维配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 模板配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 对象配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 安全配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 策略配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 管理员配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 系统配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 任务中心配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接入配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 设备中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备纳管 | 设备增删、纳管和退出，心跳维持等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备运维 | 配置已下发、升级、重启等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 升级包管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 监控大屏 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 地图 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 数据统计 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 配置中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 模板管理 | 模板和模板组的关系校验，绑定关系等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备系统管理 | 防火墙系统管理相关的配置模板，包括模板参数下发正确性、防火墙配置与网管配置数据隔离 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备对象管理 | 防火墙对象管理相关的模板，包括模板参数下发正确性、防火墙配置与网管配置数据隔离 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备安全管理 | 安全功能相关的模板，包括模板参数下发正确性、防火墙配置与网管配置数据隔离 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备策略管理 | 访问控制策略相关的模板，包括模板参数下发正确性、防火墙配置与网管配置数据隔离 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 数据中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 传输机制 | 网管和防火墙之间的数据传输机制测试，包括报文传输，丢包处理确认机制等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 设备日志 | 日志相关的数据传递、日志获取等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 任务中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 任务管理 | 任务的查看等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | IDMC系统管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 管理员管理 | IDMC的管理员登录、登出、锁定。管理员权限等 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 授权管理 | IDMC的license管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IDMC日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | IDMC升级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | 接入管理 | IDMC的管理IP和接入管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | CLI | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 性能规格 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 系统规格 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 网络层转发性能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 应用层转发性能 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 其他专项 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 安全红线 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 生产安装 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 硬件兼容性 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | 资料 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 用户手册 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | NaN | 升级指导书 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | NaN | WebUI | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |

## 耦合矩阵（数通&高可用）
| 强耦合 | 弱耦合 | 不耦合（分析责任主体） | Unnamed: 3 | Unnamed: 4 | Unnamed: 5 | Unnamed: 6 | Unnamed: 7 | Unnamed: 8 | Unnamed: 9 | Unnamed: 10 | Unnamed: 11 | Unnamed: 12 | Unnamed: 13 | Unnamed: 14 | Unnamed: 15 | Unnamed: 16 | Unnamed: 17 | Unnamed: 18 | Unnamed: 19 | Unnamed: 20 | Unnamed: 21 | Unnamed: 22 | Unnamed: 23 | Unnamed: 24 | Unnamed: 25 | Unnamed: 26 | Unnamed: 27 | Unnamed: 28 | Unnamed: 29 | Unnamed: 30 | Unnamed: 31 | Unnamed: 32 | Unnamed: 33 | Unnamed: 34 | Unnamed: 35 | Unnamed: 36 | Unnamed: 37 | Unnamed: 38 | Unnamed: 39 | Unnamed: 40 | Unnamed: 41 | Unnamed: 42 | Unnamed: 43 | Unnamed: 44 | Unnamed: 45 | Unnamed: 46 | Unnamed: 47 | Unnamed: 48 | Unnamed: 49 | Unnamed: 50 | Unnamed: 51 | Unnamed: 52 | Unnamed: 53 | Unnamed: 54 | Unnamed: 55 | Unnamed: 56 | Unnamed: 57 | Unnamed: 58 | Unnamed: 59 | Unnamed: 60 | Unnamed: 61 | Unnamed: 62 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 三级目录   |四级目录\n\n\n三级目录   |四级目录 | NaN | 物\n理\n接\n口 | 子\n接\n口 | b\nv\nI\n接\n口 | 聚\n合\n接\n口 | 隧道接口 | 安全域 | 二\n层\n转发 | 接口对 | IP\nV4\n路\n由 | IP\nV6\n路\n由 | A\nR\nP | N\nD | 策\n略\n路\n由 | ISP\n路\n由 | O\nS\nP\nF | R\nI\nP | D\nH\nC\nP | D\nN\nS | P\nP\nP\no\nE | IP\nSec\nVPN | SSL\nVPN | IP隧道 | H\nA | 链路探测 | by\nP\na\nS\nS | B\nF\nD | 带宽管理 | 黑\n白\n名\n单 | IP\nMAC\n绑\n定 | N\nA\nT | A\nS\nP\nF | 安全策略 | D\nd\no\ns | 旁路检测 | 应\n用\n识\n别 | 内容过滤 | U\nR\nL\n过\n滤 | 文件过滤 | W\nE\nB\n过滤 | 防病毒 | 入侵防御 | SSL\n卸载 | 资产管理 | 防破解 | E\nD\nR | 威胁情报 | 对象管理 | 用户管理 | 接入管理 | 启动恢复 | 系统管理 | 诊断工具 | 管理员管理 | 虚拟系统 | 升级 | S\nN\nM\nP | 授权管理 | 会话管理 | 流量统计 | 报表中心 | 日志中心 |
| 物理接口 | NaN | √ | √ | √ | √ | NaN | NaN | NaN | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 接口管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 子接口 | NaN | √ | √ | √ | √ | NaN | NaN | NaN | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 接口管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | L3子接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| bvi接口 | NaN | √ | √ | NaN | √ | NaN | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 接口管理 | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 聚合接口 | NaN | √ | √ | √ | NaN | NaN | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 手工Trunk | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | LACP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 隧道接口 | NaN | √ | √ | √ | √ | NaN | NaN | √ | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN |
| NaN | 配置管理 | √ | √ | √ | √ | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 二层转发 | NaN | √ | √ | NaN | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | vlan转发 | √ | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | mac学习 | √ | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 接口对 | NaN | √ | √ | √ | √ | NaN | NaN | √ | NaN | √ | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 接口对管理 | √ | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IPv4路由 | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 路由维护 | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IPv6路由 | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 路由维护 | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ARP | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | ARP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | ND | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ND | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | ND表 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 策略路由 | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | √ | √ | √ | NaN | NaN | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 路由管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ISP路由 | NaN | √ | √ | NaN | √ | √ | NaN | √ | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | ISP管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| OSPF | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | OSPFv2 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | OSPFv3 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| RIP | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | RIPv2 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | RIPng | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| DHCP | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | DHCPV4 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| DNS | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DNS服务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DNS中继 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DNS客户端 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DDNS | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| PPPoE | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务处理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DFX | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IPSecVpn | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | IKE协商 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | IPSec协商 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| SSLVpn | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | VPN管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 数据转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IP隧道 | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN |
| NaN | 隧道管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 6over4隧道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | GRE隧道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 4over6隧道 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| HA | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | HA管理 | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 双机热备 | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | vrrp | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| Bypass | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 安全Bypass | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 数通Bypass | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| BFD | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | BFD管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | BFD4ALL | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 带宽管理 | NaN | √ | √ | √ | √ | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 配置 管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 流分类 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 带宽限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |

## 耦合矩阵（安全&系统）
| 强耦合 | 弱耦合 | 不耦合（分析责任主体） | Unnamed: 3 | Unnamed: 4 | Unnamed: 5 | Unnamed: 6 | Unnamed: 7 | Unnamed: 8 | Unnamed: 9 | Unnamed: 10 | Unnamed: 11 | Unnamed: 12 | Unnamed: 13 | Unnamed: 14 | Unnamed: 15 | Unnamed: 16 | Unnamed: 17 | Unnamed: 18 | Unnamed: 19 | Unnamed: 20 | Unnamed: 21 | Unnamed: 22 | Unnamed: 23 | Unnamed: 24 | Unnamed: 25 | Unnamed: 26 | Unnamed: 27 | Unnamed: 28 | Unnamed: 29 | Unnamed: 30 | Unnamed: 31 | Unnamed: 32 | Unnamed: 33 | Unnamed: 34 | Unnamed: 35 | Unnamed: 36 | Unnamed: 37 | Unnamed: 38 | Unnamed: 39 | Unnamed: 40 | Unnamed: 41 | Unnamed: 42 | Unnamed: 43 | Unnamed: 44 | Unnamed: 45 | Unnamed: 46 | Unnamed: 47 | Unnamed: 48 | Unnamed: 49 | Unnamed: 50 | Unnamed: 51 | Unnamed: 52 | Unnamed: 53 | Unnamed: 54 | Unnamed: 55 | Unnamed: 56 | Unnamed: 57 | Unnamed: 58 | Unnamed: 59 | Unnamed: 60 | Unnamed: 61 | Unnamed: 62 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 三级目录   |四级目录\n\n\n三级目录   |四级目录 | NaN | 物\n理\n接\n口 | 子\n接\n口 | b\nv\nI\n接\n口 | 聚\n合\n接\n口 | 隧道接口 | 安全域 | 二\n层\n转发 | 接口对 | IP\nV4\n路\n由 | IP\nV6\n路\n由 | A\nR\nP | N\nD | 策\n略\n路\n由 | ISP\n路\n由 | O\nS\nP\nF | R\nI\nP | D\nH\nC\nP | D\nN\nS | P\nP\nP\no\nE | IP\nSec\nVPN | SSL\nVPN | IP隧道 | H\nA | 链路探测 | By\nP\nA\nS\nS | B\nF\nD | 带宽管理 | 黑\n白\n名\n单 | IP\nMAC\n绑\n定 | N\nA\nT | A\nS\nP\nF | 安全策略 | D\nd\no\ns | 旁路检测 | 应\n用\n识\n别 | 内容过滤 | U\nR\nL\n过\n滤 | 文件过滤 | W\nE\nB\n过滤 | 防病毒 | 入侵防御 | SSL\n卸载 | 资产管理 | 防破解 | E\nD\nR | 威胁情报 | 对象管理 | 用户管理 | 接入管理 | 启动恢复 | 系统管理 | 诊断工具 | 管理员管理 | 虚拟系统 | 升级 | S\nN\nM\nP | 授权管理 | 会话管理 | 流量统计 | 报表中心 | 日志中心 |
| 黑白名单 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN |
| NaN | 白名单 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 黑名单 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IPMac绑定 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ |
| NaN | 严格绑定 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 非严格绑定 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NAT | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | √ | NaN | √ |
| NaN | SNAT | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DNAT | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 静态NAT | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ASPF | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ |
| NaN | 动态端口配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 动态端口开放 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 安全策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | √ | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | IPV4策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN |
| NaN | IPV6策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN |
| NaN | 安全域 | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| Ddos | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | Ddos | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 应用识别 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | √ | √ | NaN | NaN | √ | √ | NaN | NaN | √ | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | NaN | √ |
| NaN | 应用管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 标签管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 应用规则 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 内容过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | NaN | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ |
| NaN | 过滤策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| URL过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | √ | √ | NaN | NaN | √ | √ | NaN | NaN | √ | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ |
| NaN | URL对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 过滤控制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 文件过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | √ |
| NaN | 过滤策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| WEB过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | NaN | √ | √ | √ | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | √ |
| NaN | 过滤策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 防病毒 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | NaN | √ | √ | √ | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | √ |
| NaN | 防护策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 扫描模式 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 病毒检测 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 入侵防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | √ | √ | NaN | NaN | √ | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | √ |
| NaN | 规则库 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置文件 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 入侵检测 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 弱密码防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 弱密码 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 单包防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 单包防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| DDoS防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DDoS | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 防暴力破解 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 防暴力 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| DNS检测 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN |
| NaN | DGA | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 威胁情报 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN |
| NaN | 威胁情报 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 云沙箱 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 云沙箱 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 安全分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 安全分析 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN |
| SSL卸载 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | SSL卸载 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 资产管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 资产识别 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 对象管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 地址对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 服务对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 关键字对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 时间对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 用户管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 用户配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 用户认证 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 接入管理 | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接入方式 | NaN | √ | √ | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理业务分离 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 启动恢复 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN |
| NaN | 双区启动 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 双区同步 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 数据库备份恢复 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置导入导出 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 系统管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | √ | √ | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | √ |
| NaN | 系统信息 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 系统服务 | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 诊断工具 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 实时监控 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 时间管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | √ |
| 管理员管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理员配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 认证管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 权限管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 虚拟系统 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | √ | NaN | √ | NaN | √ | NaN | NaN | √ | NaN | NaN | √ |
| 升级 | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | √ | NaN | NaN | √ |
| NaN | 升级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 回滚 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 备份同步 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| SNMP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | SNMPV1V2 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | SNMPV3 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 授权管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 授权管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | NaN | NaN | NaN | NaN | NaN |
| 会话管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ |
| NaN | 会话配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 会话控制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 会话监控 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 流量统计 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 流量监控 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 流量日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 报表中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 报表模板 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 报表任务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 历史报表 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 日志中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | √ | √ | NaN | √ | NaN | √ | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 系统日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 操作日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 防火墙日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 安全日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |

## 形态差异
| 三级目录 | 四级目录 | 责任人 | X86系列 | Unnamed: 4 | Unnamed: 5 | ARM系列 | Unnamed: 7 | Unnamed: 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NaN | NaN | NaN | J1900 | C236 | EP | 待定 | 待定 | 待定 |
| 物理接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接口管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | L2接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | L3接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 子接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接口管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | L3子接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| bvi接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接口管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 聚合接口 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 手工聚合 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 二层转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | vlan转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | mac学习 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 接口对 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接口对管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IPv4路由 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IPv6路由 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 业务转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IP邻居 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | ARP | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | IPV6邻居发现 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 策略路由 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由匹配 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ISP路由 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | ISP管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 路由转发 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| OSPF | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | OSPFv2 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| RIP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | RIP | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 等价路由 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | ECMP管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 负载均衡 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| DHCP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DHCPV4 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| DNS | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DNS | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| HA | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 双机热备 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 双机同步 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | HA管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | VRPP | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| Qos | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 带宽管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 流分类 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 带宽限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 连接限制 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 黑白名单 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 白名单 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 黑名单 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| IP/MAC绑定 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 严格绑定 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 非严格绑定 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NAT | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | SNAT | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | DNAT | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 静态NAT | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| ASPF | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 动态端口配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 动态端口开放 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 安全策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | IPV4策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | IPV6策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 安全域 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| Ddos | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | Flood防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | ARPSpoof防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | PingSweep防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | PortScan防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 应用识别 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 应用管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 标签管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 应用规则 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 内容过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 过滤策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| URL过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | URL对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 过滤策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 文件过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 过滤策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| WEB过滤 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 过滤策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 防病毒 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 防护策略 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 扫描模式 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 病毒检测 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 入侵防护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 规则库 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置文件 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 入侵检测 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理维护 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 对象管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 地址对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 服务对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 关键字对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 时间对象 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 用户管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 用户配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 用户认证 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 接入管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 接入方式 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理业务分离 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 启动恢复 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 双区启动 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 双区同步 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 数据库备份恢复 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 配置导入导出 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 系统管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 系统信息 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 系统服务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 诊断工具 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 实时监控 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 时间管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 管理员管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 管理员配置 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 认证管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 权限管理 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 升级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 升级 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 回滚 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 备份同步 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| SNMP | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | SNMPV1V2 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | SNMPV3 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 统计监控 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 流量监控 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 流量日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 报表中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 报表模板 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 报表任务 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 历史报表 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| 日志中心 | NaN | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 系统日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 操作日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 防火墙日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |
| NaN | 安全日志 | NaN | NaN | NaN | NaN | NaN | NaN | NaN |