"""Local, explicit terminology conversion; no model or remote translation service."""
from __future__ import annotations

import re


SEARCH_PREFIX = re.compile(r"^(?:请)?(?:(?:帮我|给我))?(?:检索|搜索|查找|搜|找|查)(?:一下)?")
OTHER_COMMANDS = {"帮助", "推荐", "历史", "设置", "生成推荐", "列表", "下一页", "上一页", "排序", "详情", "来源", "取消检索", "推送", "状态", "网页", "绑定"}
HAN = re.compile(r"[\u3400-\u9fff]+")
TERMS = {
    "大型语言模型": "large language model", "大语言模型": "large language model",
    "大模型": "large language model", "语言模型": "language model",
    "低秩矩阵分解": "low rank matrix decomposition", "低秩分解": "low rank decomposition",
    "奇异值分解": "singular value decomposition", "低秩近似": "low rank approximation",
    "低秩压缩": "low rank compression", "低秩适配": "low rank adaptation", "低秩": "low rank",
    "张量分解": "tensor decomposition", "矩阵分解": "matrix decomposition",
    "量化感知训练": "quantization aware training", "训练后量化": "post training quantization",
    "混合精度量化": "mixed precision quantization", "无数据量化": "data free quantization",
    "非结构化剪枝": "unstructured pruning", "结构化剪枝": "structured pruning",
    "知识蒸馏": "knowledge distillation", "自蒸馏": "self distillation",
    "模型压缩": "model compression", "压缩": "compression", "量化": "quantization",
    "剪枝": "pruning", "蒸馏": "distillation", "稀疏化": "sparsity", "稀疏": "sparse",
    "参数高效微调": "parameter efficient fine tuning", "指令微调": "instruction tuning",
    "微调": "fine tuning", "预训练": "pretraining", "推理加速": "inference acceleration",
    "推测解码": "speculative decoding", "权重": "weight", "激活": "activation",
    "多模态大模型": "multimodal large language model", "多模态": "multimodal",
    "视觉语言模型": "vision language model", "视觉模型": "vision model",
    "扩散模型": "diffusion model", "神经网络": "neural network",
    "深度学习": "deep learning", "机器学习": "machine learning",
    "强化学习": "reinforcement learning", "注意力机制": "attention mechanism",
    "检索增强生成": "retrieval augmented generation",
    "计算机视觉": "computer vision", "自然语言处理": "natural language processing",
    "目标检测": "object detection", "图像分类": "image classification",
    "图像分割": "image segmentation", "语义分割": "semantic segmentation",
    "图神经网络": "graph neural network", "图卷积网络": "graph convolutional network",
    "联邦学习": "federated learning", "持续学习": "continual learning",
    "对比学习": "contrastive learning", "自监督学习": "self supervised learning",
    "迁移学习": "transfer learning", "少样本学习": "few shot learning",
    "时间序列预测": "time series forecasting", "时间序列": "time series",
    "推荐系统": "recommender system", "知识图谱": "knowledge graph",
    "机器翻译": "machine translation", "语音识别": "speech recognition",
    "文本生成": "text generation", "代码生成": "code generation",
    "长上下文": "long context", "混合专家": "mixture of experts",
    "智能体": "agent", "思维链": "chain of thought", "幻觉": "hallucination",
    "边缘部署": "edge deployment", "边缘计算": "edge computing",
    "高效推理": "efficient inference", "分解": "decomposition",
}
TERM_PATTERN = re.compile("|".join(re.escape(term) for term in sorted(TERMS, key=len, reverse=True)))


def search_body(text: str) -> str | None:
    text = text.strip()
    if text in TERMS:
        return text
    match = SEARCH_PREFIX.match(text)
    if match:
        return text[match.end():].lstrip(" ：:")
    # A known Chinese research topic alone is also a search. Keep all existing
    # management commands explicit, even when their arguments contain topics.
    first = re.split(r"[\s|｜]", text, maxsplit=1)[0]
    if first not in OTHER_COMMANDS and TERM_PATTERN.search(text):
        return text
    return None


def english_keywords(query: str) -> str:
    """Translate known research terms; reject unknown Chinese instead of dropping it."""
    if not HAN.search(query):
        return query
    query = query.strip().strip("，。！？?!")
    query = re.sub(r"^(?:关于|有关)", "", query).strip()
    query = re.sub(r"(?:的)?(?:相关的论文|相关论文|相关研究|方面的论文|方面的研究|论文|研究)$", "", query).strip()
    translated = TERM_PATTERN.sub(lambda m: " " + TERMS[m.group()] + " ", query)
    # Only ignore the grammatical connector between recognized terms.
    translated = re.sub(r"(?<=[A-Za-z0-9])\s*(?:的|和|与|以及)\s*(?=[A-Za-z0-9])", " ", translated)
    remaining = HAN.findall(translated)
    if remaining:
        raise ValueError("还不能可靠转换这些中文内容：“" + "、".join(remaining)
                         + "”。没有发起检索。可以换个说法，或用英文表达这部分；例如“检索大模型低秩分解”。")
    return " ".join(translated.split())
