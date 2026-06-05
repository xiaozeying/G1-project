<div align="center">
  <h1 align="center"> 「元启・鸿图HongTu」 </h1>
  <h3 align="center"> 上海元启智体 </h3>
</div>

## 介绍
> ***员工双休，教程会在工作日完善，可先自己尝试，若有疑问可加群联系。***

## 同机型刷机恢复入口

如果目标是把一台同型号、刚刷机的 G1 机器尽快拉回当前这套语音主链，先不要从零手敲各子模块命令，统一从仓库根目录走恢复入口：

```bash
cd ~/HongTu
./restore_same_model_g1.sh
```

只做体检不启动服务：

```bash
./restore_same_model_g1.sh --verify-only
```

如果现场明确要启用 compose 运行面：

```bash
./restore_same_model_g1.sh --enable-compose
```

这层入口会：

- 统一 repo root / `interrupt/` / `g1-wakeword/` / `OM1/` 路径
- 自动校正 `~/HongTu -> 实际仓库根目录` 软链
- 检查关键恢复边界
- 委托 `interrupt/restore_robot_voice_chain.sh` 完成前门主链恢复

## 当前恢复边界

当前仓库已经能直接跟着 git 恢复的主要部分：

- `interrupt/`
- `g1-wakeword/`
- `G1Nav2D/src/`
- `G1Nav2D/bridge/g1_nav_bridge.py`
- `G1Nav2D/run_nav_bridge.sh`

当前还不能只靠 `git clone` 自动完整恢复的部分：

- `OM1/`
  - 目前没有完整纳入 git 跟踪
- 私有现场配置
  - `interrupt/.env.local`
- 本地 Python 运行环境
  - `interrupt/.venv`
  - `OM1/.venv-g1`
  - `wakeword-clean`
- 机器人现场设备状态
  - Pulse / USB 音频
  - 相机
  - 网络与在线服务可达性

也就是说，当前最准确的口径是：

- 这套仓库已经可以作为“同机型恢复的统一代码入口”
- 但还不是“完全不依赖现场资产的纯源码镜像”

如果缺少 `OM1/`，恢复入口会明确中止，并要求你提供：

1. 本地 `OM1/` 目录
2. 或 `interrupt/backups/private/<stamp>/om1-voice-assets.tar.gz`

## 当前推荐恢复顺序

1. 把仓库恢复到目标机器，例如 `/data/HongTu`
2. 建兼容软链：

```bash
ln -sfn /data/HongTu ~/HongTu
```

3. 确认以下目录存在：
   - `interrupt/`
   - `g1-wakeword/`
   - `OM1/` 或对应备份包
4. 执行：

```bash
./restore_same_model_g1.sh
```

5. 恢复后检查：

```bash
systemctl --user status interrupt-frontgate.service --no-pager
tail -n 80 interrupt/logs/frontgate.log
```
## 部署

### 克隆仓库
  ``` bash
  git clone https://github.com/yuanqizhiti/HongTu.git
  ```

### 2D导航
- 安装 [Livox SDK2](https://github.com/Livox-SDK/Livox-SDK2)
    ```bash
    sudo apt install cmake
    ```

    ```bash
    git clone https://github.com/Livox-SDK/Livox-SDK2.git
    cd ./Livox-SDK2/
    mkdir build
    cd build
    cmake .. && make -j
    sudo make install
    ```

- 更改雷达ip及地图保存路径
  ``` bash
  # 修改本机与雷达ip
  cd HongTu/G1Nav2D/src/livox_ros_driver2-master/config/
  gedit MID360_config.json
  
  # 修改地图保存路径，将该文件下最底部路径改为自己的电脑
  cd HongTu/G1Nav2D/src/fastlio2/src/
  gedit map_builder_node.cpp
  ```

- 编译程序
  ``` bash
  cd HongTu/G1Nav2D/
  catkin_make
  
  #遇到报错可先执行以下命令
  cd HongTu/G1Nav2D/src/livox_ros_driver2-master/
  ./build.sh ROS1
  cd HongTu/G1Nav2D/
  catkin_make
  ```

- 安装依赖包
  ``` bash
  sudo apt install ros-noetic-teb-local-planner ros-noetic-global-planner ros-noetic-costmap-server
  ```

- 建图及保存
  ``` bash
  # 建图
  cd HongTu/G1Nav2D/
  source devel/setup.bash
  roslaunch fastlio mapping.launch
  
  # 打开新终端
  cd HongTu/G1Nav2D/
  source devel/setup.bash
  # 保存地图，自定义路径及地图名称
  rosrun map_server map_saver map:=/projected_map -f /home/nvidia/mymap
  ```

- 编辑地图
  ``` bash
  # 打开地图，利用Map Eraser Tool修改地图，ctrl+加号或减号可修改画笔大小，保存地图
  source devel/setup.bash
  roslaunch ros_map_edit map_edit.launch
  ```

- 开启导航
  ``` bash
  #修改地图路径
  cd HongTu/G1Nav2D/src/fastlio2/config/
  gedit gridmap_load.launch
  
  # 启动导航，启动导航后需自行按照雷达位置重定位
  cd HongTu/G1Nav2D/
  source devel/setup.bash
  roslaunch fastlio navigation.launch
  ```

- 启动运控  
安装unitree_sdk2_python参考[宇树官方文档](https://github.com/unitreerobotics/unitree_sdk2_python.git)
  ``` bash
  # 打开新终端，网口可通过ifconfig命令查询自行更改
  cd HongTu/unitree_sdk2_python/example/g1/high_level/
  python3 g1_control.py 网口
  ```
在rviz中发布目标点即可自主导航

### 语音交互
基于[pyxiaozhi](https://github.com/huangjunsen0406/py-xiaozhi)，ubuntu20.04默认python版本不符合，安装小智需要配置虚拟环境。
- 基础要求
    Python版本：3.9 - 3.12
    操作系统：Windows 10+、macOS 10.15+、Linux
    音频设备：麦克风和扬声器设备
    网络连接：稳定的互联网连接（用于AI服务和在线功能）

- 安装依赖
  ``` bash
  cd PythonProject/py-xiaozhi-main/
  pip install -r requirements.txt
  ```
  
- 语音导航至目标点简易版
  1. 全局搜索关键词“电梯”，将所有“电梯”替换成你需要的关键词，例如“卧室”、“卫生间”等。
  2. 在Pythonproject/point_nav/point2.py修改改点坐标，修改位置在该程序最底部。（坐标可以通过导航发布目标点时，监听/move_base/goal话题获取，手动输入，当前为测试版本，每个目标点为不同的启动程序）
 
- 导航到目标点MCP服务
  ``` bash
  #以导航至电梯目标点为例
  # 在该文件的第1232行，修改或添加导航至目标点的关键词
  PythonProject/py-xiaozhi-main/src/application.py
  
  # 在该文件的第334行，修改或添加mcp服务的注册信息
  PythonProject/py-xiaozhi-main/src/mcp/mcp_server.py
  
  #在该文件的第15至第17行，选择该mcp服务拉起的python程序，以及启动该程序的编译器路径
  PythonProject/py-xiaozhi-main/src/mcp/tools/daohang_dianti/tools.py
  
  #在该文件的第10至第13行，选择拉起的导航点程序，以及启动该程序的编译器路径
  PythonProject/daohang/daohang-dianti.py
  
  #在该文件修改目标点的坐标
  PythonProject/point_nav/point1.py
  ```

- 启动语音程序
  ``` bash
  cd PythonProject/py-xiaozhi-main/
  python3 main.py
  ```
实现语音交互导航需要同时开启语音、运控、导航。

## 公司招聘
招聘岗位：  
- Slam导航算法工程师  
- 嵌入式工程师  
- 结构工程师

其余相关研发岗位均在招聘中，欢迎联系。  
  
公司地址：上海市浦东新区张江机器人谷  
投递邮箱：707556641@qq.com  

## 联系方式及打赏
<table style="margin: 0 auto;">
  <tr>
    <!-- 第一张图：固定宽度200px，居中显示 -->
    <td style="padding: 0 10px; text-align: center;">
      <img src="wxzhifu.jpeg" alt="vx支付" width="300" style="height: auto;">
    </td>
    <!-- 第二张图：与第一张保持相同宽度 -->
    <td style="padding: 0 10px; text-align: center;">
      <img src="contact" alt="dayiqun" width="300" style="height: auto;">
    </td>
  </tr>
</table>
