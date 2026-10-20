import re
import uuid
from langchain_core.documents import Document


SECTION_PATTERN = re.compile(
    r"(?m)^(?P<section_number>\d+\.\d+)\s+"
    r"(?P<title>[^\n]+)$"
)

ALARM_CODE_PATTERN = re.compile(
    r"\bE-\d{3}\b"
)


def split_by_section(
    documents: list[Document],
) -> list[Document]:

    sections: list[Document] = []

    for document in documents:

        text = document.page_content
        page = document.metadata["page"]
        # 当前测试手册的第 2 页是目录页，
        # 不参与章节解析和知识索引。
        if page == 2:
            continue

        matches = list(
            SECTION_PATTERN.finditer(text)
        )

        if not matches:
            continue

        for index, match in enumerate(matches):

            start = match.start()

            if index + 1 < len(matches):
                end = matches[index + 1].start()
            else:
                end = len(text)

            section_text = text[start:end].strip()

            section_number = match.group(
                "section_number"
            )

            title = match.group(
                "title"
            ).strip()

            is_continuation = title.endswith(
                "（续）"
            )

            if (
                is_continuation
                and sections
                and sections[-1].metadata[
                    "section_number"
                ] == section_number
            ):
                previous_section = sections[-1]

                previous_section.page_content += (
                    "\n\n" + section_text
                )

                previous_section.metadata[
                    "page_end"
                ] = page

                continue

            section = Document(
                page_content=section_text,
                metadata={
                    **document.metadata,
                    "section_number": section_number,
                    "section_title": title,
                    "page_start": page,
                    "page_end": page,
                },
            )

            sections.append(section)

    return sections


def extract_alarm_code(
    text: str,
) -> str | None:

    match = ALARM_CODE_PATTERN.search(
        text
    )

    if match is None:
        return None

    return match.group(0)


def split_text_with_overlap(
    text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[str]:

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size 必须大于 0"
        )

    if chunk_overlap < 0:
        raise ValueError(
            "chunk_overlap 不能小于 0"
        )

    if chunk_overlap >= chunk_size:
        raise ValueError(
            "chunk_overlap 必须小于 chunk_size"
        )

    text = text.strip()

    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []

    start = 0

    while start < len(text):

        end = min(
            start + chunk_size,
            len(text),
        )

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end == len(text):
            break

        start = end - chunk_overlap

    return chunks


def get_overlap_lines(
    lines: list[str],
    chunk_overlap: int,
) -> list[str]:

    if chunk_overlap <= 0:
        return []

    overlap_lines: list[str] = []
    overlap_length = 0

    for line in reversed(lines):

        extra_length = (
            len(line)
            if not overlap_lines
            else len(line) + 1
        )

        if (
            overlap_length + extra_length
            > chunk_overlap
        ):
            break

        overlap_lines.append(line)
        overlap_length += extra_length

    overlap_lines.reverse()

    return overlap_lines


def split_text_by_lines(
    text: str,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[str]:
    """
    优先按照完整行进行文本切分。

    设计目标：
    1. 尽量不从一行中间切断文本；
    2. 每个 Chunk 尽量不超过 chunk_size；
    3. 相邻 Chunk 尽量保留 chunk_overlap 长度的完整行；
    4. 如果单独一行已经超过 chunk_size，
       则使用 split_text_with_overlap() 进行字符级兜底切分。
    """

    # ============================================================
    # 1. 清理文本
    # ============================================================

    text = text.strip()

    # 如果文本为空，直接返回空列表
    if not text:
        return []

    # 如果整段文本本身就没有超过 chunk_size，
    # 那么不需要继续切分
    if len(text) <= chunk_size:
        return [text]

    # ============================================================
    # 2. 将文本拆成一行一行
    # ============================================================

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    # 最终已经完成的 Chunks
    chunks: list[str] = []

    # 当前正在组装的 Chunk
    current_lines: list[str] = []

    # 当前 Chunk 的字符长度
    current_length = 0

    # ============================================================
    # 3. 逐行处理
    # ============================================================

    for line in lines:

        line_length = len(line)

        # --------------------------------------------------------
        # 情况 A：
        # 当前这一行自己就已经超过 chunk_size
        # --------------------------------------------------------

        if line_length > chunk_size:

            # 如果之前已经积累了一些正常文本，
            # 先把它们保存成一个 Chunk
            if current_lines:

                chunks.append(
                    "\n".join(current_lines)
                )

                # 当前 Chunk 已经保存，
                # 所以清空状态
                current_lines = []
                current_length = 0

            # 这一行本身太长，
            # 无法继续按照“完整行”处理，
            # 所以调用字符级 overlap 切分函数兜底
            long_line_chunks = (
                split_text_with_overlap(
                    text=line,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
            )

            # 把切出来的多个 Chunk
            # 一个一个加入最终 chunks
            chunks.extend(long_line_chunks)

            # 当前超长行已经处理完成，
            # 直接进入下一轮循环
            continue

        # --------------------------------------------------------
        # 情况 B：
        # 当前这一行长度正常
        # --------------------------------------------------------

        # 如果 current_lines 为空，
        # 当前行直接加入，不需要额外的换行符
        #
        # 如果 current_lines 已经有内容，
        # 加入新行时，中间还会增加一个 "\n"
        extra_length = (
            line_length
            if not current_lines
            else line_length + 1
        )

        # --------------------------------------------------------
        # 情况 B1：
        # 当前 Chunk + 新行 <= chunk_size
        #
        # 说明还能继续往当前 Chunk 里面装
        # --------------------------------------------------------

        if (
            current_length + extra_length
            <= chunk_size
        ):

            current_lines.append(line)

            current_length += extra_length

        # --------------------------------------------------------
        # 情况 B2：
        # 当前 Chunk + 新行 > chunk_size
        #
        # 说明当前 Chunk 已经装不下这一行了
        # --------------------------------------------------------

        else:

            # 先把当前 Chunk 保存下来
            chunks.append(
                "\n".join(current_lines)
            )

            # ----------------------------------------------------
            # 从刚刚完成的 Chunk 尾部，
            # 取出一些完整行作为 overlap
            # ----------------------------------------------------

            overlap_lines = get_overlap_lines(
                lines=current_lines,
                chunk_overlap=chunk_overlap,
            )

            # 尝试：
            #
            # 上一个 Chunk 的 overlap
            # +
            # 当前这一行
            #
            # 一起作为新 Chunk 的开始
            candidate_lines = (
                overlap_lines + [line]
            )

            # 计算这个候选 Chunk 的真实长度
            candidate_length = len(
                "\n".join(candidate_lines)
            )

            # ----------------------------------------------------
            # 如果 overlap + 当前行
            # 仍然没有超过 chunk_size
            #
            # 那么保留 overlap
            # ----------------------------------------------------

            if candidate_length <= chunk_size:

                current_lines = candidate_lines

                current_length = candidate_length

            # ----------------------------------------------------
            # 如果 overlap + 当前行
            # 已经超过 chunk_size
            #
            # 那么放弃 overlap，
            # 直接让当前行成为新 Chunk 的第一行
            # ----------------------------------------------------

            else:

                current_lines = [line]

                current_length = line_length

    # ============================================================
    # 4. 保存最后一个还没有封箱的 Chunk
    # ============================================================

    # for 循环结束以后，
    # current_lines 中可能还剩下一部分文本。
    #
    # 因为后面已经没有新的 line，
    # 所以不会再触发上面的 else。
    #
    # 因此这里必须手动保存最后一个 Chunk。
    if current_lines:

        chunks.append(
            "\n".join(current_lines)
        )

    # ============================================================
    # 5. 返回最终所有 Chunk
    # ============================================================

    return chunks


def build_chunk_id(
    source: str,
    section_number: str,
    page_start: int,
    page_end: int,
    chunk_index: int,
    chunk_text: str,
) -> str:

    identity = (
        f"{source}|"
        f"{section_number}|"
        f"{page_start}|"
        f"{page_end}|"
        f"{chunk_index}|"
        f"{chunk_text}"
    )

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            identity,
        )
    )


def has_section_body(
    section_text: str,
) -> bool:

    lines = [
        line.strip()
        for line in section_text.splitlines()
        if line.strip()
    ]

    if len(lines) <= 1:
        return False

    body_lines = lines[1:]

    body_text = "\n".join(
        body_lines
    ).strip()

    if not body_text:
        return False

    return True



def chunk_sections(
    sections: list[Document],
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[Document]:

    # ============================================================
    # 1. 创建列表，用于保存最终生成的所有 Chunk Documents
    # ============================================================

    chunk_documents: list[Document] = []

    # ============================================================
    # 2. 一个 Section 一个 Section 地处理
    # ============================================================

    for section in sections:

        # --------------------------------------------------------
        # 获取当前 Section 的正文
        # --------------------------------------------------------

        section_text = section.page_content

        # --------------------------------------------------------
        # 获取 Section 标题
        #
        # 例如：
        # "E-103 电机过热报警"
        # --------------------------------------------------------

        section_title = section.metadata.get(
            "section_title",
            "",
        )

        # ========================================================
        # 3. 过滤只有标题、没有正文的伪 Section
        # ========================================================

        # 例如 PDF 目录中可能存在：
        #
        # 3.3 E-103 电机过热报警
        #
        # 但后面没有真正的故障描述、原因、排查步骤等正文。
        #
        # 这种 Section 不应该进入向量数据库。
        if not has_section_body(
            section_text
        ):
            continue

        # ========================================================
        # 4. 获取 Section 的 metadata
        # ========================================================

        # 获取 Section 编号
        #
        # 例如：
        # "3.3"
        section_number = section.metadata.get(
            "section_number",
            "",
        )

        # 获取来源文件名
        #
        # 例如：
        # "industrial_robot_maintenance_manual.pdf"
        source = section.metadata.get(
            "source",
            "unknown",
        )

        # 获取 Section 起始页
        #
        # 例如：
        # 6
        page_start = section.metadata.get(
            "page_start",
            0,
        )

        # 获取 Section 结束页
        #
        # 如果没有 page_end，
        # 默认使用 page_start
        page_end = section.metadata.get(
            "page_end",
            page_start,
        )

        # ========================================================
        # 5. 从 Section 标题中提取报警代码
        # ========================================================

        # 例如：
        #
        # "E-103 电机过热报警"
        #
        # ↓
        #
        # "E-103"
        #
        # 如果标题中没有报警代码，
        # extract_alarm_code() 返回 None
        alarm_code = extract_alarm_code(
            section_title
        )

        # ========================================================
        # 6. 将当前 Section 切成一个或多个文本 Chunk
        # ========================================================

        text_chunks = split_text_by_lines(
            text=section_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        # ========================================================
        # 7. 给当前 Section 产生的每个 Chunk 编号
        # ========================================================

        for chunk_index, chunk_text in enumerate(
            text_chunks
        ):

            # ====================================================
            # 8. 为当前 Chunk 生成确定性的 chunk_id
            # ====================================================

            chunk_id = build_chunk_id(
                source=source,
                section_number=section_number,
                page_start=page_start,
                page_end=page_end,
                chunk_index=chunk_index,
                chunk_text=chunk_text,
            )

            # ====================================================
            # 9. 将普通字符串包装成 LangChain Document
            # ====================================================

            chunk_document = Document(
                page_content=chunk_text,
                metadata={
                    # 继承原 Section 的 metadata
                    #
                    # 包括：
                    # source
                    # source_path
                    # page
                    # section_number
                    # section_title
                    # page_start
                    # page_end
                    **section.metadata,

                    # 新增 Chunk 级别的 metadata
                    "alarm_code": alarm_code,
                    "chunk_index": chunk_index,
                    "chunk_id": chunk_id,
                },
            )

            # ====================================================
            # 10. 保存最终 Chunk
            # ====================================================

            chunk_documents.append(
                chunk_document
            )

    # ============================================================
    # 11. 所有 Section 处理完成
    # ============================================================

    return chunk_documents