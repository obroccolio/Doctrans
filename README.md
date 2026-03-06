# Doctrans - 文档翻译工具

使用大模型 API 自动翻译 PowerPoint 和 PDF 文件，尽量保持原有排版和样式。

## 功能特点

- **Web 页面**: 提供浏览器上传和下载界面
- **命令行模式**: 支持脚本和直接命令两种方式
- **自定义 API**: 支持任何 OpenAI 兼容格式的 API
- **保持排版**: 翻译后尽量保留原有样式、字体、位置
- **批量处理**: 支持多文件和目录批量翻译
- **智能缓存**: 相同文本只翻译一次，节省 API 调用
- **中文字体**: 自动为中文内容设置合适字体
- **进度显示**: 实时显示翻译进度

## 安装

```bash
cd Doctrans
pip3 install -r requirements.txt
```

## 配置

复制示例配置并按需修改：

```bash
cp config/config.example.yaml config/config.yaml
```

编辑 `config/config.yaml`：

```yaml
llm:
  base_url: "https://api.openai.com/v1"  # 你的 API 地址
  api_key: ""  # 可直接写在配置里，但会优先使用环境变量 LLM_API_KEY / OPENAI_API_KEY
  model: "gpt-4o-mini"

translation:
  source_lang: "en"
  target_lang: "zh"

output:
  chinese_font: "PingFang SC"  # Mac: PingFang SC, Windows: Microsoft YaHei
  suffix: "_translated"
```

设置 API 密钥（优先级高于配置文件）：

```bash
export LLM_API_KEY="your-api-key"
```

## 快速启动

### 启动 Web 页面

项目内置了一键启动脚本：

```bash
bash start.sh
```

脚本会自动：

- 创建 `.venv` 虚拟环境（如不存在）
- 安装 `requirements.txt` 中的依赖
- 启动 Web 服务

启动后访问：

```text
http://localhost:8020
```

如果你想手动启动 Web 服务，也可以直接运行：

```bash
python -m uvicorn src.web:app --host 0.0.0.0 --port 8020
```

### 使用快速翻译脚本

命令行模式也提供了快捷脚本：

```bash
bash translate.sh presentation.pptx
```

脚本会自动创建/复用 `.venv`，然后执行：

```bash
python -m src.main "$@"
```

## 使用方法

### 基本使用（Mac 请使用 `python3`）

```bash
# 翻译单个 PPT
python -m src.main presentation.pptx

# 翻译单个 PDF
python -m src.main document.pdf

# 指定输出文件
python -m src.main input.pptx -o output.pptx
```

### 批量翻译

```bash
# 翻译整个目录
python -m src.main ./ppts/ -o ./output/

# 翻译多个文件
python -m src.main file1.pptx file2.pptx file3.pptx
```

### 命令行选项

```bash
python -m src.main input.pptx \
  --base-url https://api.example.com/v1 \
  --api-key your-key \
  --model gpt-4o \
  --source en \
  --target zh
```

| 选项 | 说明 |
|------|------|
| `-o, --output` | 输出文件或目录 |
| `--base-url` | 自定义 API 地址 |
| `--api-key` | API 密钥 |
| `--model` | 模型名称 |
| `--source` | 源语言代码 (en, zh, ja...) |
| `--target` | 目标语言代码 |
| `--config` | 配置文件路径 |

## 项目结构

```text
Doctrans/
├── src/
│   ├── main.py          # CLI 入口
│   ├── web.py           # Web 服务入口
│   ├── templates/
│   │   └── index.html   # Web 页面
│   ├── ppt_reader.py    # PPT 读取
│   ├── ppt_writer.py    # PPT 写入
│   ├── pdf_reader.py    # PDF 读取
│   ├── pdf_writer.py    # PDF 写入
│   ├── translator.py    # 翻译协调
│   └── llm/
│       ├── base.py      # LLM 基类
│       └── openai_client.py  # OpenAI 兼容客户端
├── config/
│   └── config.example.yaml   # 配置示例
├── start.sh            # Web 一键启动脚本
├── translate.sh        # CLI 快捷脚本
└── requirements.txt
```

## License

MIT
