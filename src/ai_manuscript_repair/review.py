from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from pydantic import BaseModel

from ai_manuscript_repair.models import (
    ConsistencyCluster,
    ConsistencyClusterDraft,
    ConsistencyOccurrenceDraft,
    ConsistencyWindowReview,
    DirectBatchReview,
    PagePacket,
    compact_text,
)


DIRECT_PROMPT_VERSION = "ai-manuscript-minimal-repair-v1"
CONSISTENCY_PROMPT_VERSION = "ai-manuscript-local-consistency-v1"

DIRECT_INSTRUCTIONS = """你是中文图书的精修编辑。稿件已经接收，不能退稿，也不能改写成另一篇文章。请通读核心页面和相邻上下文，先理解作者原本想表达的意思，再把不合出版要求的语言逐处修成可用文本。理解范围可以覆盖整段，但每项修改必须局部、最小、可直接执行。

只处理能够直接落实的语言问题：指代不清，施事、动作与受事错位，词语搭配不当，修饰关系含混，术语或近义词堆叠，机械重复，混合比喻，并列层级不一致，连接关系不成立，论断强度失真，空泛自我评价，无实际作用的强调，以及明确的句法、标点和用词错误。句子表面通顺不等于达到出版要求，但普通连接词、宣传口吻、比喻或重复本身也不是错误。

约束：
1. 保留作者观点、信息、语气和段落次序，不新增事实或论据，不提高思想水平，不整段重写。
2. 能换一个词解决就不改分句，能改分句解决就不改整句。
3. original_text 必须逐字取自对应 page_text，并包含足以定位的最短完整上下文；同文多次出现时 occurrence_index 从0开始。
4. corrected_text 必须给出 original_text 的完整改后文本，替换后可以直接成句。删除时使用空字符串。
5. reason 只供内部审计，用短语说明具体语言问题。
6. 不做事实核查、作者询问、结构建议、图片意见、版式意见或AI来源判断。
7. 不设修改数量目标；没有可直接修改的问题时返回空 edits。
8. 只为 core_packet_ids 返回 review，每个核心页面恰好一条；batch_id 原样返回。"""

CONSISTENCY_INSTRUCTIONS = """你是中文图书的局部语义一致性审校员。请理解连续正文中的对象、角色、功能、流程、步骤和概念，找出同一局部语义单元中很可能指向同一对象或承担同一固定功能、但前后使用不同名称或角色层级的表达。

你的任务只是发现需要编辑人工判断是否统一的候选簇，不选择规范说法，不提出修改意见。应报告同一AI角色的称谓漂移，同一系统、模块、成果物、操作步骤或核心概念换了叫法，以及可能需要人工判断的广义称谓到专业身份的具体化。

不要报告普通动词、形容词或连接词的自然替换，不同对象恰好使用近义词，人称代词与先行词的正常替换，或已经明确定义且不造成漂移的简称与全称。

约束：
1. 不设候选数量目标或上限。
2. 每个 cluster 至少包含两个不同表面说法，并列出簇内所有可精确定位的出现位置。
3. original_text 必须逐字复制自对应 page_text，尽量只取称谓或角色的最短完整片段；同页同文多次出现时 occurrence_index 从0开始。
4. 不返回改文、规范形式、建议、理由或面向编辑的说明。object_summary 和 relation_type 只供内部归并。
5. 只有至少一个 occurrence 位于 core_packet_ids 时才返回该簇；上下文页中的同簇 occurrence 也应列出。
6. 没有候选时返回空 clusters；window_id 原样返回。"""


def strict_schema(model: type[BaseModel]) -> dict[str, object]:
    schema = model.model_json_schema()

    def require_all(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
            for value in node.values():
                require_all(value)
        elif isinstance(node, list):
            for value in node:
                require_all(value)

    require_all(schema)
    return schema


def _review_hash(prompt_version: str, packets: Sequence[PagePacket]) -> str:
    payload = json.dumps(
        {
            "prompt_version": prompt_version,
            "packets": [item.packet_sha256 for item in packets],
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _packet_payload(packet: PagePacket) -> dict[str, object]:
    return {
        "packet_id": packet.packet_id,
        "pdf_page_index": packet.pdf_page_index,
        "pdf_page_number": packet.pdf_page_index + 1,
        "page_text": packet.page_text,
    }


@dataclass(frozen=True)
class DirectBatch:
    batch_id: str
    review_sha256: str
    core_packet_ids: tuple[str, ...]
    packets: tuple[PagePacket, ...]


@dataclass(frozen=True)
class ConsistencyWindow:
    window_id: str
    review_sha256: str
    core_packet_ids: tuple[str, ...]
    packets: tuple[PagePacket, ...]


def build_direct_batches(
    packets: Sequence[PagePacket],
    *,
    batch_size: int = 8,
    context_pages: int = 1,
) -> list[DirectBatch]:
    if batch_size < 1 or context_pages < 0:
        raise ValueError("batch_size must be positive and context_pages nonnegative")
    ordered = sorted(packets, key=lambda item: item.pdf_page_index)
    result: list[DirectBatch] = []
    for start in range(0, len(ordered), batch_size):
        core = ordered[start : start + batch_size]
        visible = ordered[
            max(0, start - context_pages) : min(
                len(ordered), start + batch_size + context_pages
            )
        ]
        result.append(
            DirectBatch(
                batch_id=(
                    f"DB-P{core[0].pdf_page_index + 1:04d}-"
                    f"P{core[-1].pdf_page_index + 1:04d}"
                ),
                review_sha256=_review_hash(DIRECT_PROMPT_VERSION, visible),
                core_packet_ids=tuple(item.packet_id for item in core),
                packets=tuple(visible),
            )
        )
    return result


def build_consistency_windows(
    packets: Sequence[PagePacket],
    *,
    core_size: int = 8,
    context_pages: int = 1,
) -> list[ConsistencyWindow]:
    if core_size < 1 or context_pages < 0:
        raise ValueError("core_size must be positive and context_pages nonnegative")
    ordered = sorted(packets, key=lambda item: item.pdf_page_index)
    result: list[ConsistencyWindow] = []
    for start in range(0, len(ordered), core_size):
        core = ordered[start : start + core_size]
        visible = ordered[
            max(0, start - context_pages) : min(
                len(ordered), start + core_size + context_pages
            )
        ]
        result.append(
            ConsistencyWindow(
                window_id=(
                    f"CW-P{core[0].pdf_page_index + 1:04d}-"
                    f"P{core[-1].pdf_page_index + 1:04d}"
                ),
                review_sha256=_review_hash(CONSISTENCY_PROMPT_VERSION, visible),
                core_packet_ids=tuple(item.packet_id for item in core),
                packets=tuple(visible),
            )
        )
    return result


def direct_prompt(batch: DirectBatch) -> str:
    payload = {
        "batch_id": batch.batch_id,
        "core_packet_ids": list(batch.core_packet_ids),
        "pages": [_packet_payload(item) for item in batch.packets],
    }
    return DIRECT_INSTRUCTIONS + "\n\n页面数据：\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )


def consistency_prompt(window: ConsistencyWindow) -> str:
    payload = {
        "window_id": window.window_id,
        "core_packet_ids": list(window.core_packet_ids),
        "pages": [_packet_payload(item) for item in window.packets],
    }
    return CONSISTENCY_INSTRUCTIONS + "\n\n页面数据：\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    )


def _locatable(packet: PagePacket, text: str, occurrence_index: int) -> bool:
    needle = compact_text(text)
    haystack = "".join(item.text for item in packet.glyphs)
    matches = 0
    cursor = 0
    while needle:
        found = haystack.find(needle, cursor)
        if found < 0:
            break
        if matches == occurrence_index:
            return True
        matches += 1
        cursor = found + 1
    return False


def validate_direct_review(review: DirectBatchReview, batch: DirectBatch) -> None:
    if review.batch_id != batch.batch_id:
        raise ValueError("model returned wrong batch_id")
    if {item.packet_id for item in review.reviews} != set(batch.core_packet_ids):
        raise ValueError("model must return exactly one review per core page")
    by_id = {item.packet_id: item for item in batch.packets}
    for page_review in review.reviews:
        packet = by_id[page_review.packet_id]
        if page_review.pdf_page_index != packet.pdf_page_index:
            raise ValueError("review page does not match packet")
        for edit in page_review.edits:
            if not _locatable(packet, edit.original_text, edit.occurrence_index):
                raise ValueError(
                    f"direct edit is not locatable: {packet.packet_id} "
                    f"{edit.original_text!r} occurrence {edit.occurrence_index}"
                )


def validate_consistency_review(
    review: ConsistencyWindowReview,
    window: ConsistencyWindow,
) -> None:
    if review.window_id != window.window_id:
        raise ValueError("model returned wrong window_id")
    by_id = {item.packet_id: item for item in window.packets}
    core = set(window.core_packet_ids)
    for cluster in review.clusters:
        if not any(item.packet_id in core for item in cluster.occurrences):
            raise ValueError("cluster has no occurrence on a core page")
        for occurrence in cluster.occurrences:
            packet = by_id.get(occurrence.packet_id)
            if packet is None:
                raise ValueError("occurrence packet is outside the window")
            if occurrence.pdf_page_index != packet.pdf_page_index:
                raise ValueError("occurrence page does not match packet")
            if not _locatable(
                packet, occurrence.original_text, occurrence.occurrence_index
            ):
                raise ValueError(
                    f"consistency occurrence is not locatable: "
                    f"{packet.packet_id} {occurrence.original_text!r}"
                )


class CodexReviewer:
    def __init__(
        self,
        *,
        model: str = "gpt-5.6-sol",
        reasoning_effort: str = "medium",
        executable: str | None = None,
        working_directory: Path | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.executable = executable
        self.working_directory = working_directory or Path(tempfile.gettempdir())
        self._codex = None

    async def __aenter__(self) -> CodexReviewer:
        from openai_codex import AsyncCodex, CodexConfig

        self._codex = AsyncCodex(
            CodexConfig(
                codex_bin=self.executable,
                cwd=str(self.working_directory),
                config_overrides=(
                    "features.apps=false",
                    "features.plugins=false",
                    "features.browser_use=false",
                    "features.computer_use=false",
                    "features.image_generation=false",
                    "features.in_app_browser=false",
                    "features.memories=false",
                ),
            )
        )
        await self._codex.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._codex is not None:
            await self._codex.__aexit__(exc_type, exc, traceback)
            self._codex = None

    async def _run(
        self,
        prompt: str,
        response_model: type[BaseModel],
    ) -> tuple[BaseModel, dict[str, Any]]:
        if self._codex is None:
            raise RuntimeError("CodexReviewer must be used as a context manager")
        from openai_codex import ApprovalMode, Sandbox, TextInput

        thread = await self._codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            base_instructions=(
                "Do not use tools or inspect files. Review only the supplied "
                "page text and return the required structured response."
            ),
            cwd=str(self.working_directory),
            ephemeral=True,
            model=self.model,
            sandbox=Sandbox.read_only,
        )
        result = await thread.run(
            [TextInput(prompt)],
            approval_mode=ApprovalMode.deny_all,
            effort=self.reasoning_effort,
            model=self.model,
            output_schema=strict_schema(response_model),
            sandbox=Sandbox.read_only,
        )
        if result.error is not None:
            raise RuntimeError(f"Codex SDK turn failed: {result.error}")
        if not result.final_response:
            raise RuntimeError("Codex SDK turn returned no final response")
        response = response_model.model_validate_json(result.final_response)
        metadata = {
            "thread_id": thread.id,
            "turn_id": result.id,
            "duration_ms": result.duration_ms,
            "usage": (
                result.usage.model_dump(mode="json", by_alias=True)
                if result.usage is not None
                else None
            ),
        }
        return response, metadata

    async def direct(self, batch: DirectBatch) -> tuple[DirectBatchReview, dict[str, Any]]:
        response, metadata = await self._run(
            direct_prompt(batch), DirectBatchReview
        )
        assert isinstance(response, DirectBatchReview)
        validate_direct_review(response, batch)
        return response, metadata

    async def consistency(
        self, window: ConsistencyWindow
    ) -> tuple[ConsistencyWindowReview, dict[str, Any]]:
        response, metadata = await self._run(
            consistency_prompt(window), ConsistencyWindowReview
        )
        assert isinstance(response, ConsistencyWindowReview)
        validate_consistency_review(response, window)
        return response, metadata


async def _cached_review(
    *,
    cache_path: Path,
    review_sha256: str,
    response_model: type[BaseModel],
    runner,
    retries: int,
) -> BaseModel:
    if cache_path.is_file():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if payload.get("review_sha256") == review_sha256:
            return response_model.model_validate(payload["response"])
    last_error: Exception | None = None
    for attempt in range(1, retries + 2):
        try:
            response, metadata = await runner()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "review_sha256": review_sha256,
                        "attempts": attempt,
                        "response": response.model_dump(mode="json"),
                        "provider": metadata,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return response
        except Exception as exc:  # retry provider and validation failures
            last_error = exc
    assert last_error is not None
    raise last_error


async def run_reviews(
    packets: Sequence[PagePacket],
    output_dir: Path,
    *,
    model: str = "gpt-5.6-sol",
    reasoning_effort: str = "medium",
    concurrency: int = 3,
    batch_size: int = 8,
    context_pages: int = 1,
    retries: int = 1,
    include_consistency: bool = False,
) -> tuple[list[DirectBatchReview], list[ConsistencyWindowReview]]:
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    direct_batches = build_direct_batches(
        packets, batch_size=batch_size, context_pages=context_pages
    )
    windows = (
        build_consistency_windows(
            packets, core_size=batch_size, context_pages=context_pages
        )
        if include_consistency
        else []
    )
    semaphore = asyncio.Semaphore(concurrency)
    async with CodexReviewer(
        model=model,
        reasoning_effort=reasoning_effort,
        working_directory=output_dir,
    ) as reviewer:
        async def one_direct(batch: DirectBatch) -> DirectBatchReview:
            async with semaphore:
                response = await _cached_review(
                    cache_path=output_dir / "run" / "direct" / f"{batch.batch_id}.json",
                    review_sha256=batch.review_sha256,
                    response_model=DirectBatchReview,
                    runner=lambda: reviewer.direct(batch),
                    retries=retries,
                )
                assert isinstance(response, DirectBatchReview)
                validate_direct_review(response, batch)
                return response

        direct = await asyncio.gather(*(one_direct(item) for item in direct_batches))

        async def one_window(window: ConsistencyWindow) -> ConsistencyWindowReview:
            async with semaphore:
                response = await _cached_review(
                    cache_path=(
                        output_dir / "run" / "consistency" / f"{window.window_id}.json"
                    ),
                    review_sha256=window.review_sha256,
                    response_model=ConsistencyWindowReview,
                    runner=lambda: reviewer.consistency(window),
                    retries=retries,
                )
                assert isinstance(response, ConsistencyWindowReview)
                validate_consistency_review(response, window)
                return response

        consistency = await asyncio.gather(*(one_window(item) for item in windows))
    return list(direct), list(consistency)


def _occurrence_key(item: ConsistencyOccurrenceDraft) -> tuple[object, ...]:
    return (
        item.packet_id,
        item.pdf_page_index,
        item.original_text,
        item.occurrence_index,
    )


def consolidate_clusters(
    reviews: Sequence[ConsistencyWindowReview],
) -> list[ConsistencyCluster]:
    drafts: list[ConsistencyClusterDraft] = [
        cluster for review in reviews for cluster in review.clusters
    ]
    groups: list[list[ConsistencyClusterDraft]] = []
    for draft in drafts:
        draft_keys = {_occurrence_key(item) for item in draft.occurrences}
        overlapping = [
            index
            for index, group in enumerate(groups)
            if draft_keys
            & {
                _occurrence_key(item)
                for existing in group
                for item in existing.occurrences
            }
        ]
        if not overlapping:
            groups.append([draft])
            continue
        first = overlapping[0]
        groups[first].append(draft)
        for index in reversed(overlapping[1:]):
            groups[first].extend(groups.pop(index))

    clusters: list[ConsistencyCluster] = []
    for cluster_number, group in enumerate(groups, start=1):
        occurrences: dict[tuple[object, ...], ConsistencyOccurrenceDraft] = {}
        for draft in group:
            for item in draft.occurrences:
                occurrences.setdefault(_occurrence_key(item), item)
        ordered = sorted(
            occurrences.values(),
            key=lambda item: (
                item.pdf_page_index,
                item.original_text,
                item.occurrence_index,
            ),
        )
        clusters.append(
            ConsistencyCluster(
                cluster_id=f"LCC-{cluster_number:04d}",
                object_summaries=sorted({item.object_summary for item in group}),
                relation_types=sorted({item.relation_type for item in group}),
                occurrences=ordered,
            )
        )
    return clusters
