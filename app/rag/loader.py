from pathlib import Path

import pymupdf

from langchain_core.documents import Document


def load_pdf(
    file_path: str | Path,
) -> list[Document]:
    """
    加载 PDF 文件，并按页转换成 LangChain Document。

    每一页对应一个 Document，
    同时保留 source、page 等元数据。
    """

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"PDF 文件不存在: {file_path}"
        )

    if file_path.suffix.lower() != ".pdf":
        raise ValueError(
            f"当前只支持 PDF 文件: {file_path}"
        )

    pdf = pymupdf.open(file_path)

    documents: list[Document] = []

    try:
        for page_index in range(
            len(pdf)
        ):
            page = pdf[page_index]

            text = page.get_text(
                "text"
            )

            if not text.strip():
                continue

            document = Document(
                page_content=text,
                metadata={
                    "source": file_path.name,
                    "source_path": str(file_path),
                    "page": page_index + 1,
                },
            )

            documents.append(
                document
            )

    finally:
        pdf.close()

    return documents
