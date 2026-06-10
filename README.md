# 高校跨实验室智能预约与精细化管理平台

这是一个 `Streamlit + MongoDB` 原型平台，覆盖管理员、教师、学生三类角色，用于演示和试运行跨实验室预约、课表占用拦截、设备台账、审批闭环、设备报修和运行数据看板。

## 一键启动

双击 `start_platform.bat`。脚本会自动检查并启动 MongoDB、初始化必要数据，然后启动 Streamlit 平台。

启动完成后，窗口会显示可访问地址：

```text
Local: http://127.0.0.1:8501
LAN:   http://本机局域网IP:8501
```

本机使用 `Local` 地址。其他电脑必须和本机连接到同一个 Wi-Fi 或有线局域网，然后打开 `LAN` 地址。

## 局域网访问

平台网页服务监听 `0.0.0.0:8501`，因此同一局域网内的其他电脑可以通过本机 IP 访问。MongoDB 仍然只绑定 `127.0.0.1:27017`，不会直接暴露给其他电脑。

如果其他电脑打不开 `http://本机局域网IP:8501`：

1. 确认本机平台已经启动。
2. 确认两台电脑在同一个 Wi-Fi 或有线局域网。
3. 以管理员身份运行 PowerShell，然后执行：

```powershell
cd /d E:\codex
.\configure_firewall_8501.ps1
```

4. 如果当前网络是“公用网络”，建议先在 Windows 网络设置中改为“专用网络”。
5. 如果仍无法访问，可能是学校网络或路由器开启了客户端隔离，需要换到允许设备互访的局域网，或部署到固定服务器。

## 云端部署

如果希望“只要联网就能访问”，推荐使用你之前熟悉的 `Streamlit Cloud + MongoDB Atlas` 架构。部署说明见：

```text
STREAMLIT_CLOUD_DEPLOY.md
```

这个方式不需要本机一直开机，也不需要手动启动 MongoDB。Streamlit Cloud 负责公网网站，MongoDB Atlas 负责云数据库，数据库连接串放在 Streamlit Cloud Secrets 中。`STREAMLIT_CLOUD_DEPLOY.md` 是一步一步的上架教程，适合按步骤照做。

如果后续要部署到自己购买的 Linux 云服务器，也可以使用项目内的服务器部署脚本：

```text
CLOUD_DEPLOY.md
deploy/install_cloud_ubuntu.sh
deploy/lab-platform.service
deploy/nginx-lab-platform.conf.template
deploy/backup_mongodb.sh
```

在本机生成上传包：

```powershell
.\deploy\package_for_cloud.ps1
```

生成的压缩包位于 `dist` 目录。上传到云服务器后，按 `CLOUD_DEPLOY.md` 操作即可。

## 手动启动

1. 安装依赖：

```powershell
pip install -r requirements.txt
```

2. 启动 MongoDB，默认连接为 `mongodb://localhost:27017`：

```powershell
.\run_mongodb.bat
```

3. 初始化演示数据：

```powershell
python seed_data.py
```

4. 启动平台：

```powershell
.\run_app.bat
```

## 真实数据导入

管理员登录后可在后台导入真实数据：

- 设备台账：进入 `设备台账`，上传 Excel。
- 课表占用：进入 `课表`，上传教务系统导出的教室课表打印 `.xls` 文件，设置第 1 周周一和节次时间后导入。
- 开放记录：进入 `预约记录`，点击 `导出开放预约记录`，按当前状态筛选直接导出开放记录。

导入课表或设备前，请先在 `实验室` 页面维护实验室名称，Excel 中的实验室名称需要与平台中一致。

## 演示账号

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | admin | admin123 |
| 教师 | teacher_xun | teacher123 |
| 学生 | student_li | student123 |

## 核心规则

- 同一实验室同一时间段允许多人预约。
- 实验室正式上课时间段禁止预约。
- 同一设备同一时间段不可重复预约，除非设备被标记为可共享设备。
- 设备利用率按已通过或已完成预约的使用时长占开放时长比例计算。
- 学生和教师可在设备状态页提交设备报修，管理员可处理并同步更新设备状态。
- 管理员处理报修时可同步生成维护日志，并可重置用户密码。
- 开放记录导出使用内置模板，从第 4 行开始写入数据，学时按 45 分钟折算。
