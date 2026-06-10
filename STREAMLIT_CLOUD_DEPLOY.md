# Streamlit Cloud + MongoDB Atlas 傻瓜式上架教程

目标：把当前平台发布到公网。发布完成后，别人只要联网，打开 Streamlit Cloud 给你的网址，就可以登录使用平台。

本教程适合当前项目：

- 网页应用：Streamlit Cloud
- 云数据库：MongoDB Atlas
- 入口文件：`app.py`
- 数据库名：`lab_management_platform`

官方参考：

- Streamlit Cloud 部署文档：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app
- Streamlit Cloud Secrets 文档：https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- MongoDB Atlas 入门文档：https://www.mongodb.com/docs/get-started/
- MongoDB Atlas IP Access List 文档：https://www.mongodb.com/docs/atlas/security/ip-access-list/

---

## 一、先看最终效果

部署完成后，你会得到一个网址，通常类似：

```text
https://你的应用名.streamlit.app
```

其他人打开这个网址后，会看到平台登录页。登录后可以按角色使用：

- 管理员：审批预约、处理报修、导入课表、导出开放记录
- 教师：预约、查看课表占用、查看设备状态、提交报修
- 学生：预约、查看课表占用、查看设备状态、提交报修

---

## 二、你需要准备什么

请先准备 3 个账号或资源：

1. GitHub 账号
2. Streamlit Community Cloud 账号
3. MongoDB Atlas 账号

如果你之前简易网站已经用过这个架构，通常这三个账号已经有了。

---

## 三、确认项目文件

你现在的项目目录是：

```text
E:\codex
```

需要上传到 GitHub 的核心文件和目录：

```text
app.py
requirements.txt
seed_data.py
README.md
STREAMLIT_CLOUD_DEPLOY.md
lab_platform/
templates/
.streamlit/config.toml
.streamlit/secrets.toml.example
.gitignore
```

不要上传这些文件或目录：

```text
.env
.streamlit/secrets.toml
mongodb/
mongodb-data/
mongodb-log/
mongodb-windows-x86_64-8.2.3.zip
dist/
__pycache__/
*.log
```

项目已经写好了 `.gitignore`，正常用 Git 上传时会自动忽略这些内容。

---

## 四、上传项目到 GitHub

### 方法 A：用 GitHub Desktop，推荐

1. 打开 GitHub Desktop。
2. 点击左上角 `File`。
3. 点击 `Add local repository...`。
4. 选择项目目录：

```text
E:\codex
```

5. 如果提示这个文件夹还不是 Git 仓库，选择 `create a repository`。
6. Repository name 可以填：

```text
lab-management-platform
```

7. 确认 `.gitignore` 存在。
8. 在左下角 Summary 写：

```text
Initial Streamlit Cloud deployment
```

9. 点击 `Commit to main`。
10. 点击 `Publish repository`。
11. 如果只是自己部署，可以先选 `Private`。Streamlit Cloud 只要授权 GitHub 后也能读取私有仓库。
12. 发布完成后，记住 GitHub 仓库地址，例如：

```text
https://github.com/你的用户名/lab-management-platform
```

### 方法 B：用 GitHub 网页上传，不推荐但能用

如果你不会用 GitHub Desktop，也可以网页上传，但要特别小心别把本地 MongoDB 和压缩包传上去。

1. 打开 GitHub。
2. 点击右上角 `+`。
3. 点击 `New repository`。
4. Repository name 填：

```text
lab-management-platform
```

5. 创建仓库。
6. 点击 `uploading an existing file`。
7. 只上传本教程第三部分列出的核心文件和目录。
8. 不要上传 `mongodb`、`mongodb-data`、`mongodb-log`、`dist`。

这个方法容易漏文件或传错文件，所以更推荐 GitHub Desktop。

---

## 五、创建 MongoDB Atlas 云数据库

### 1. 创建项目

1. 打开 MongoDB Atlas。
2. 登录账号。
3. 如果没有 Project，点击 `New Project`。
4. Project 名称可以填：

```text
Lab Management Platform
```

5. 创建 Project。

### 2. 创建 Cluster

1. 进入 Project。
2. 点击 `Create` 或 `Build a Database`。
3. 选择免费或低配集群。
   - 演示和小范围试运行：免费集群通常够用。
   - 如果后面很多人同时用，再升级。
4. 云厂商和地区可以默认，也可以选离你更近的地区。
5. Cluster 名称可以填：

```text
lab-platform-cluster
```

6. 点击创建。
7. 等几分钟，直到 Cluster 状态变成可用。

---

## 六、创建数据库账号

这个账号是平台连接数据库用的，不是你登录 Atlas 网站的账号。

1. 在 Atlas 左侧找到 `Database Access`。
2. 点击 `Add New Database User`。
3. Authentication Method 选择 `Password`。
4. Username 填：

```text
lab_platform_user
```

5. Password 建议点击自动生成，或者自己设置一个强密码。
6. 密码请先临时保存到本地安全位置，后面要填连接串。
7. 权限选择：
   - 简单做法：`Read and write to any database`
   - 更稳妥做法：只给 `lab_management_platform` 数据库读写权限
8. 点击 `Add User`。

注意：密码里如果有 `@`、`#`、`%`、`/`、`:` 这类特殊字符，连接串可能需要 URL 编码。为了少踩坑，建议密码先用大小写字母、数字和下划线组合。

---

## 七、开放 Atlas 网络访问

Streamlit Cloud 的出口 IP 不是你本机 IP，所以 Atlas 需要允许 Streamlit Cloud 访问。

1. 在 Atlas 左侧找到 `Network Access`。
2. 点击 `Add IP Address`。
3. 第一版推荐点击 `Allow Access from Anywhere`。
4. 它会添加：

```text
0.0.0.0/0
```

5. 点击 Confirm 或 Save。

说明：

- 这个设置表示允许任何来源尝试连接 Atlas。
- 真正能连接成功还需要数据库用户名和密码。
- 因此数据库密码必须足够强。
- 如果以后要更高安全性，可以换成固定云服务器部署方案。

---

## 八、复制 Atlas 连接串

1. 回到 Atlas 的 Database 或 Clusters 页面。
2. 找到你的 Cluster。
3. 点击 `Connect`。
4. 选择 `Drivers`。
5. Driver 选择 Python。
6. 复制连接串，形状大概是：

```text
mongodb+srv://<username>:<password>@lab-platform-cluster.xxxxx.mongodb.net/?retryWrites=true&w=majority
```

7. 把 `<username>` 换成数据库用户名：

```text
lab_platform_user
```

8. 把 `<password>` 换成数据库密码。
9. 建议在域名后面加上数据库名 `lab_management_platform`，最终类似：

```text
mongodb+srv://lab_platform_user:你的密码@lab-platform-cluster.xxxxx.mongodb.net/lab_management_platform?retryWrites=true&w=majority
```

这个连接串后面要填到 Streamlit Cloud Secrets 里。不要发到 GitHub。

---

## 九、部署到 Streamlit Cloud

### 1. 新建 App

1. 打开 Streamlit Community Cloud。
2. 登录账号。
3. 点击 `Create app` 或 `New app`。
4. 选择 `Deploy a public app from GitHub` 或类似选项。
5. 授权 Streamlit 访问你的 GitHub。
6. 选择刚才上传的仓库，例如：

```text
你的用户名/lab-management-platform
```

### 2. 填部署信息

按下面填写：

```text
Repository: 你的 GitHub 仓库
Branch: main
Main file path: app.py
App URL: 可以自定义一个短名字
```

App URL 例如：

```text
lab-management-platform
```

最后的网址可能类似：

```text
https://lab-management-platform.streamlit.app
```

---

## 十、填写 Streamlit Secrets

这是最关键的一步。没有 Secrets，平台连不上 Atlas。

### 如果还没点 Deploy

1. 在创建 App 页面找到 `Advanced settings`。
2. 找到 `Secrets` 输入框。
3. 填入下面内容：

```toml
MONGODB_URI = "mongodb+srv://lab_platform_user:你的密码@lab-platform-cluster.xxxxx.mongodb.net/lab_management_platform?retryWrites=true&w=majority"
MONGODB_DB = "lab_management_platform"
```

4. 把里面的连接串换成你自己的真实连接串。
5. 点击 Save。
6. 再点击 Deploy。

### 如果已经 Deploy 了

1. 进入 Streamlit Cloud 的 App 页面。
2. 点击右下角或右上角的 `Manage app`。
3. 点击 `Settings`。
4. 找到 `Secrets`。
5. 粘贴：

```toml
MONGODB_URI = "mongodb+srv://lab_platform_user:你的密码@lab-platform-cluster.xxxxx.mongodb.net/lab_management_platform?retryWrites=true&w=majority"
MONGODB_DB = "lab_management_platform"
```

6. 点击 Save。
7. 点击 `Reboot app` 或等待自动重启。

注意：

- 这里填的是 TOML 格式。
- 等号两边可以有空格。
- 连接串必须放在英文双引号里。
- 不要把真实连接串写进 GitHub 文件。

---

## 十一、等待 Streamlit 构建完成

部署后 Streamlit 会自动安装依赖。它会读取：

```text
requirements.txt
```

当前项目依赖包括：

```text
streamlit
pymongo
pandas
plotly
xlrd
openpyxl
```

如果部署成功，你会看到应用页面。

如果构建失败，先看 Streamlit Cloud 的日志，常见问题在本教程后面有排查方法。

---

## 十二、初始化 Atlas 数据

首次部署后，Atlas 数据库是空的。你需要运行一次 `seed_data.py`，创建演示账号和基础数据。

### 方法 A：在本机 PowerShell 执行，推荐

1. 打开 PowerShell。
2. 进入项目目录：

```powershell
cd /d E:\codex
```

3. 设置 Atlas 连接串：

```powershell
$env:MONGODB_URI="mongodb+srv://lab_platform_user:你的密码@lab-platform-cluster.xxxxx.mongodb.net/lab_management_platform?retryWrites=true&w=majority"
$env:MONGODB_DB="lab_management_platform"
```

4. 执行初始化：

```powershell
python seed_data.py
```

如果你的电脑上 `python` 命令不可用，可以用项目当前可用的 Python：

```powershell
C:\Users\pc\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe seed_data.py
```

5. 看到没有报错，就说明初始化成功。

### 方法 B：用 Streamlit Cloud 的网页功能初始化

当前项目没有做“网页一键初始化 Atlas”的按钮，因此第一版请用方法 A。

---

## 十三、第一次登录测试

打开 Streamlit Cloud 生成的网址，例如：

```text
https://lab-management-platform.streamlit.app
```

用下面账号登录：

| 角色 | 账号 | 初始密码 |
| --- | --- | --- |
| 管理员 | admin | admin123 |
| 教师 | teacher_xun | teacher123 |
| 学生 | student_li | student123 |

正式使用前，请先用管理员账号登录，然后重置默认密码。

---

## 十四、完整功能验收清单

请按下面顺序测试。

### 1. 登录测试

1. 管理员登录成功。
2. 教师登录成功。
3. 学生登录成功。

### 2. 预约测试

1. 用学生账号提交一条预约。
2. 用教师账号提交一条预约。
3. 用管理员账号查看预约记录。
4. 管理员通过或驳回预约。
5. 学生或教师查看“我的预约”，确认状态变化。

### 3. 课表冲突测试

1. 管理员导入教务课表打印 `.xls`。
2. 学生或教师选择上课时间段预约。
3. 平台应该提示冲突，禁止提交。

### 4. 重复实验室预约测试

1. 同一实验室、非上课时间段，提交多条预约。
2. 平台应该允许重复预约。

### 5. 设备冲突测试

1. 选择一个不可共享设备。
2. 同一时间段提交两条预约。
3. 第二条应该被拦截。

### 6. 设备报修测试

1. 学生或教师进入设备状态。
2. 提交一条设备报修。
3. 管理员进入设备报修。
4. 管理员更新为处理中、已修复或已关闭。

### 7. 开放记录导出测试

1. 管理员进入预约记录。
2. 点击导出开放预约记录。
3. 下载 Excel。
4. 确认表头、格式、学时、人数、设备等字段正常。

---

## 十五、上线后必须做的安全动作

### 1. 修改默认密码

管理员账号默认是：

```text
admin / admin123
```

上线后必须修改。

### 2. 不要公开 Atlas 密码

真实连接串只能放在：

```text
Streamlit Cloud -> App -> Settings -> Secrets
```

不要放到：

```text
README.md
GitHub Issue
微信群
截图
.env
.streamlit/secrets.toml
```

### 3. 如果密码泄露

立刻做三件事：

1. 去 Atlas 重置 Database User 密码。
2. 去 Streamlit Cloud Secrets 更新 `MONGODB_URI`。
3. 重启 Streamlit App。

如果密码已经提交到 GitHub，删除文件还不够，因为 Git 历史里可能还在。最稳妥是直接重置 Atlas 密码。

---

## 十六、常见问题排查

### 问题 1：Streamlit 页面显示无法连接 MongoDB

优先检查：

1. Streamlit Cloud Secrets 是否填了 `MONGODB_URI`。
2. `MONGODB_URI` 是否有英文双引号。
3. Atlas 用户名和密码是否正确。
4. Atlas Network Access 是否添加了 `0.0.0.0/0`。
5. 连接串里是否写了数据库名 `lab_management_platform`。

### 问题 2：Streamlit Cloud 构建失败

检查日志里是否出现依赖安装错误。

确认 GitHub 仓库里有：

```text
requirements.txt
```

确认里面有：

```text
streamlit>=1.36
pymongo>=4.7
pandas>=2.0
plotly>=5.22
xlrd>=2.0.1
openpyxl>=3.1
```

### 问题 3：导出开放记录时报模板不存在

确认 GitHub 仓库里有：

```text
templates/开放记录导出模板.xlsx
```

不要只上传 Python 文件，模板文件也必须上传。

### 问题 4：上传课表 `.xls` 后解析失败

确认上传的是教务系统“教室课表打印”格式，不是普通 Excel 表格。

当前平台专门适配的是你之前提供的 `课表打印+(92).xls` 这种结构。

### 问题 5：初始化数据后还是登录不了

检查 `seed_data.py` 连接的是不是同一个 Atlas 数据库。

PowerShell 里重新确认：

```powershell
echo $env:MONGODB_URI
echo $env:MONGODB_DB
```

如果本机初始化到了本地 MongoDB，而 Streamlit Cloud 连的是 Atlas，就会出现云端没账号的情况。

### 问题 6：Atlas 连接串密码包含特殊符号

如果密码有这些符号：

```text
@ # % / : ? & =
```

连接串可能解析失败。最简单的处理方式：

1. 去 Atlas 重置数据库用户密码。
2. 新密码使用大小写字母、数字、下划线。
3. 更新 Streamlit Cloud Secrets。

---

## 十七、每次改代码后怎么更新网站

以后你修改了本地代码，需要让线上网站更新：

1. 把修改提交到 GitHub。
2. Streamlit Cloud 通常会自动重新部署。
3. 如果没有自动部署，进入 App 管理页面，点击 Reboot 或 Redeploy。
4. 打开线上网址测试。

如果只改了 Streamlit Secrets：

1. 保存 Secrets。
2. Reboot app。
3. 不需要重新上传 GitHub。

---

## 十八、最短上架流程

如果你只想看最短流程，按这个做：

1. 用 GitHub Desktop 把 `E:\codex` 发布到 GitHub。
2. 去 Atlas 创建 Cluster。
3. 去 Atlas 创建 Database User。
4. 去 Atlas Network Access 添加 `0.0.0.0/0`。
5. 复制 Atlas Python 连接串。
6. 去 Streamlit Cloud 创建 App，入口填 `app.py`。
7. 在 Streamlit Secrets 填：

```toml
MONGODB_URI = "你的 Atlas 连接串"
MONGODB_DB = "lab_management_platform"
```

8. 等 Streamlit 部署完成。
9. 本机运行：

```powershell
cd /d E:\codex
$env:MONGODB_URI="你的 Atlas 连接串"
$env:MONGODB_DB="lab_management_platform"
python seed_data.py
```

10. 打开 Streamlit Cloud 网址，用 `admin / admin123` 登录。

---

## 十九、你完成后需要保存的信息

请把下面信息保存到一个安全位置：

```text
GitHub 仓库地址：
Streamlit Cloud 网站地址：
MongoDB Atlas 项目名：
MongoDB Atlas Cluster 名：
MongoDB Atlas 数据库用户名：
管理员账号：
管理员新密码：
```

不要把 Atlas 数据库密码写到公开文档里。
