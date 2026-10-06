import argparse
import logging
import os
import sys
from pathlib import Path

# 支持直接执行该脚本；先设置 app 路径，再导入项目模块。
project_root = Path(__file__).resolve().parents[3]
app_path = project_root / "app"
if str(app_path) not in sys.path:
    sys.path.insert(0, str(app_path))

# 先加载 .env，再导入其他模块（确保 Milvus 配置正确）
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)






EMBEDDING_MODEL = "text-embedding-v1"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _collect_paths(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in {".txt", ".md", ".markdown"}:
            raise ValueError("只支持 UTF-8 编码的 .txt、.md、.markdown 文件")
        return [input_path]
    patterns = ("*.txt", "*.md", "*.markdown")
    paths: list[Path] = []
    for pat in patterns:
        paths.extend(sorted(input_path.rglob(pat)))
    return paths


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="导入 UTF-8 文本到本地知识库")
    parser.add_argument("input", type=Path, help="文本文件或目录")
    parser.add_argument("--collection", help="覆盖知识库集合名")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(str(input_path))
    paths = _collect_paths(input_path)
    if not paths:
        raise ValueError(f"未找到可入库文件: {input_path}")

    from mult_agents.config import AppConfig
    from mult_agents.rag.core import RAGSystem, RAGConfig

    config = AppConfig.from_file()
    collection_name = args.collection or os.getenv("KNOWLEDGE_COLLECTION") or config.milvus_collection
    rag_cfg = RAGConfig(
        milvus_host=config.milvus_host,
        milvus_port=config.milvus_port,
        collection_name=collection_name,
        embedding_model=EMBEDDING_MODEL,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    rag = RAGSystem(api_key=config.api_key, config=rag_cfg)

    total_chunks = rag.ingest_paths(paths)
    print(f"入库完成 | 文件数={len(paths)} | chunk数={total_chunks} | collection={collection_name}")


if __name__ == "__main__":
    main()
