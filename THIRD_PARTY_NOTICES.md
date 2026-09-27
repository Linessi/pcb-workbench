# 第三方来源与许可

本项目原创代码和文档采用根目录 Apache-2.0。第三方作品仍遵循各自许可；本项目名称不代表嘉立创官方产品。

## 实际包含的代码

- [easyeda/pro-api-sdk](https://github.com/easyeda/pro-api-sdk)，本地基线 1.6.27，Apache-2.0，Copyright [2024] JLCEDA。保留 `extension/LICENSE` 与 NOTICE。`extension/build/`、构建配置和部分扩展脚手架源自该 SDK；本项目修改了入口、多面板构建配置、打包输出目录和扩展元数据。未引入旧 SDK Git 历史。
- 扩展图标为本项目绘制的简单几何图形，不使用嘉立创商标图标。

## 通过依赖管理器安装

Node 构建依赖及 API 类型声明由 `extension/package-lock.json` 锁定；它们不是后端安装包中的依赖目录。构建由 esbuild、TypeScript、ts-node、JSZip、fs-extra 等完成；相应许可随各依赖分发。

Python 运行依赖包括 FastAPI、Uvicorn、Pydantic Settings、OpenAI SDK、Pillow、Sentence Transformers、FAISS 及传递依赖，版本见 `backend/requirements*.txt`。后端包仅包含源码和依赖声明，不打包上述库、系统字体或模型权重。

设计检查首次检索会下载 [BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)；权重不在本仓库和 Release 中，使用遵循模型来源许可。

## 知识规则与演示材料

`knowledge/pcb_rules.md` 是带来源链接的简短设计规则摘要，不包含厂商手册全文。链接保留以便核对原始说明。

历史开发使用过 Twisted Fields 的 RP2040 板，原作者 Taylor Alexander / Twisted Fields LLC，CERN-OHL-P v2。本公开快照不捆绑该硬件工程或其截图，不声称该硬件由本项目设计。测试夹具是合成数据。

yt-dlp 与 biosshot/easyeda-copilot 仅作为发布组织方式参考，没有复制其代码、文档或截图。
