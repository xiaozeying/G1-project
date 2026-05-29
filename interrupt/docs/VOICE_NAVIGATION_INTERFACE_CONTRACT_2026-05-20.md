# 语音导航接口契约

更新时间：2026-05-20

## 1. 边界定义

`interrupt` 只负责语音导航接口层，不负责导航算法、地图构建、定位、规划器、Nav2 或 move_base 运行时维护。

`interrupt` 的职责只有三件事：

- 把用户自然语言稳定映射成导航工具调用
- 通过统一导航适配层把请求发给机器人现有导航后端
- 在后端不可用、超时、缺配置时返回清晰失败

以下内容不属于 `interrupt` 交付范围：

- `g1_3d_nav` / `G1Nav2D` / `Nav2` / `move_base` 的安装、编译、运行
- 地图文件、waypoint 文件、点位文件的生产流程
- 机器人导航工作区 overlay 失效、依赖缺失、消息包缺失
- 定位精度、规划效果、运动控制效果

## 2. 上层语音工具面

当前语音导航工具口固定为：

- `list_saved_locations`
- `navigate_to_saved_location(location)`
- `remember_current_location(location, description="")`

其中：

- `location` 是用户可说出的地点名
- `description` 仅作为可选补充，不影响主导航流程

## 3. 适配层对外契约

`interrupt` 内部统一走 `G1Om1Adapter`，由：

- `INTERRUPT_G1_NAV_PROVIDER`
- `INTERRUPT_G1_NAV_BASE_URL`
- `INTERRUPT_G1_NAVIGATION_SCRIPT`
- `INTERRUPT_G1_NAV_BRIDGE_RUNNER`

控制最终对接面。

当前推荐：

- `INTERRUPT_G1_NAV_PROVIDER=g1_3d_nav`
- `INTERRUPT_G1_NAV_BASE_URL=http://localhost:5000`

## 4. HTTP 兼容接口

为了让语音层不感知底层导航栈差异，导航桥需要对外暴露这组兼容接口：

- `GET /healthz`
- `GET /maps/locations/list`
- `POST /navigate/location`
- `POST /maps/locations/add/slam`
- `POST /start/nav2`
- `POST /stop/nav2`

其中：

- `GET /maps/locations/list` 返回当前可导航地点列表
- `POST /navigate/location` 接收 `{"label": "<地点名>"}` 或 `{"location": "<地点名>"}`
- `POST /maps/locations/add/slam` 接收 `{"label": "<地点名>"}` 为主

## 5. 兼容的数据面

`interrupt` 当前允许后端自行使用以下任一数据面，只要最终能提供上面的 HTTP 兼容接口即可：

- `waypoints.yaml + NavigateToPose`
- `*_point.json + move_base`
- 其他内部点位格式

`interrupt` 不要求导航侧必须统一成某一种地图/点位格式。

## 6. 失败语义

如果导航后端不可用，`interrupt` 只需要保证：

- 不误触发机器人运动
- 不伪造成功
- 向用户返回清晰的“导航后端当前不可用”语义

当前典型失败包括：

- `localhost:5000` 无监听
- 桥接进程未启动
- 地点不存在
- 导航工作区依赖缺失
- `nav2_msgs` / `move_base` 等运行时不可导入

这些都应被视为“导航后端不可用”，而不是“语音接口层失败”。

## 7. 当前收口结论

截至 2026-05-20，`interrupt` 侧已经完成：

- 语音导航工具口固定
- `g1_3d_nav` provider 接入
- 兼容 HTTP bridge 入口补齐
- 机器人现有 `waypoints.yaml` 运行面识别完成

当前剩余未收口项属于导航后端运行时，而不属于 `interrupt` 接口层。
