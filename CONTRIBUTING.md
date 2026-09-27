# 参与开发

使用 Python 3.12 和 Node.js 24。先阅读使用说明与现有接口；所有 EDA 调用须核对安装的 SDK 类型声明。

```powershell
cd extension
npm ci
npx tsc --noEmit
npm run lint
npm run build
npm test
cd ..
py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-lock-windows-py312.txt
cd backend
.venv/Scripts/python.exe -m pytest -q
```

自动测试包含受控模型与 EDA 替身，用于接口、数据保护和状态机回归，不代替客户端实机测试。合成夹具保留原测试的计数与字段断言；不依赖开发者的历史 output。

提交前确认不含配置秘密、运行数据和私有板文件。补充问题复现及受影响回归，保留数据与版本兼容。不得自动放宽保真、来源或外发范围校验。

## 打包发布

从待发布提交的干净 checkout 构建扩展，随后运行 `python scripts/package_release.py --output ../release-assets`。脚本只打包 Git 跟踪的后端、规则与部署材料，并生成校验和；不打包工作目录中的运行数据。

发布为公开预览版，标签、代码和资产版本一致。ZIP 内文件时间统一以提交时间为基准；SDK 的 eext 打包时间可能导致二次构建哈希变化，不承诺逐字节确定性。
